"""API HTTP assíncrona para iniciar e consultar análises científicas."""

from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import json
from copy import deepcopy
from io import BytesIO
import logging
from pathlib import Path
import sqlite3
from time import perf_counter
from threading import Lock
from typing import Any, Callable, Iterator, Mapping, Protocol
from uuid import uuid4

from flask import Flask, Response, g, jsonify, request, send_file, url_for
from werkzeug.utils import secure_filename

from .analysis_service import AnalysisServiceError, MultiArticleAnalysis
from .article_ingestion import (
    ArticleIngestionError,
    ArticleFirstAnalysisRunner,
    ArticleSubmission,
    ExtractedClaim,
    PreparedArticle,
    validate_article_submission,
)
from .library import ArticleLibrary
from .document_parsing import DocumentParsingError
from .article_ingestion import ResolvedArticleDocument
from .gemini_evidence import GeminiAnalysisError
from .pubmed import PubMedError
from .topic_search import PubMedTopicSearch
from .topic_clustering import TopicClusteringError
from .report_export import render_markdown_report
from .research_plan import SEARCH_DEPTHS
from .input_validation import AnalysisInput, InputValidationError, validate_analysis_input
from .web_ui import register_web_ui
from .verification_cards import build_analysis_cards
from .structured_logging import bind_log_context, log_event, logged_step
from .structured_sources import StructuredSourceError


logger = logging.getLogger(__name__)


class AnalysisRunner(Protocol):
    """Contrato mínimo do pipeline chamado em segundo plano."""

    def analyze(
        self,
        claim: str,
        article_reference: str | None = None,
    ) -> MultiArticleAnalysis: ...


class ArticleAnalysisRunner(Protocol):
    def analyze_article(self, submission: ArticleSubmission) -> Mapping[str, Any]: ...

    def prepare_article(self, submission: ArticleSubmission) -> PreparedArticle: ...

    def preparation_result(self, prepared: PreparedArticle) -> Mapping[str, Any]: ...

    def analyze_prepared(
        self,
        prepared: PreparedArticle,
        selected_claims: tuple[ExtractedClaim, ...] | None = None,
        depth: str = "QUICK",
    ) -> Mapping[str, Any]: ...


class StudyToolsRunner(Protocol):
    def reassess_with_full_text(
        self,
        claim_result: Mapping[str, Any],
        *,
        claim_text: str,
        claim_profile: Mapping[str, Any] | None,
        study_key: str,
        pdf_bytes: bytes,
    ) -> Mapping[str, Any]: ...

    def find_new_studies(self, claim_result: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def complementary_search(
        self,
        claim_result: Mapping[str, Any],
        *,
        claim_text: str,
        claim_profile: Mapping[str, Any] | None,
        excluded_dois: tuple[str, ...] = (),
    ) -> Mapping[str, Any]: ...


class AnalysisJobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    AWAITING_CLAIM_SELECTION = "AWAITING_CLAIM_SELECTION"
    RESEARCHING = "RESEARCHING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class AnalysisJob:
    analysis_id: str
    claim: str
    article_reference: str | None
    status: AnalysisJobStatus
    progress: int
    created_at: str
    updated_at: str
    result: Mapping[str, Any] | None = None
    error: Mapping[str, str] | None = None
    workflow: Mapping[str, Any] | None = None


class AnalysisJobNotFoundError(LookupError):
    """O identificador não pertence a uma análise conhecida."""


ALLOWED_JOB_TRANSITIONS = {
    AnalysisJobStatus.QUEUED: {
        AnalysisJobStatus.RUNNING,
        AnalysisJobStatus.FAILED,
    },
    AnalysisJobStatus.RUNNING: {
        AnalysisJobStatus.AWAITING_CLAIM_SELECTION,
        AnalysisJobStatus.SUCCEEDED,
        AnalysisJobStatus.FAILED,
    },
    AnalysisJobStatus.AWAITING_CLAIM_SELECTION: {
        AnalysisJobStatus.RESEARCHING,
        AnalysisJobStatus.FAILED,
    },
    AnalysisJobStatus.RESEARCHING: {
        AnalysisJobStatus.RESEARCHING,
        AnalysisJobStatus.SUCCEEDED,
        AnalysisJobStatus.FAILED,
    },
    AnalysisJobStatus.SUCCEEDED: {AnalysisJobStatus.RESEARCHING},
    AnalysisJobStatus.FAILED: {AnalysisJobStatus.RESEARCHING},
}


class AnalysisJobStore(Protocol):
    def create(self, analysis_input: AnalysisInput) -> AnalysisJob: ...

    def get(self, analysis_id: str) -> AnalysisJob: ...

    def transition(
        self,
        analysis_id: str,
        *,
        status: AnalysisJobStatus,
        progress: int,
        result: Mapping[str, Any] | None = None,
        error: Mapping[str, str] | None = None,
        workflow: Mapping[str, Any] | None = None,
    ) -> AnalysisJob: ...

    def update_result(self, analysis_id: str, result: Mapping[str, Any]) -> AnalysisJob: ...

    def list_ids(self, status: AnalysisJobStatus) -> list[str]: ...


class InMemoryAnalysisJobStore:
    """Armazena snapshots de trabalhos com transições protegidas por lock."""

    _ALLOWED_TRANSITIONS = ALLOWED_JOB_TRANSITIONS

    def __init__(self) -> None:
        self._jobs: dict[str, AnalysisJob] = {}
        self._lock = Lock()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create(self, analysis_input: AnalysisInput) -> AnalysisJob:
        timestamp = self._now()
        job = AnalysisJob(
            analysis_id=str(uuid4()),
            claim=analysis_input.claim,
            article_reference=analysis_input.article_reference,
            status=AnalysisJobStatus.QUEUED,
            progress=0,
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self._lock:
            self._jobs[job.analysis_id] = job
        return job

    def get(self, analysis_id: str) -> AnalysisJob:
        with self._lock:
            job = self._jobs.get(analysis_id)
        if job is None:
            raise AnalysisJobNotFoundError(
                f"A análise {analysis_id!r} não foi encontrada."
            )
        return job

    def transition(
        self,
        analysis_id: str,
        *,
        status: AnalysisJobStatus,
        progress: int,
        result: Mapping[str, Any] | None = None,
        error: Mapping[str, str] | None = None,
        workflow: Mapping[str, Any] | None = None,
    ) -> AnalysisJob:
        if not 0 <= progress <= 100:
            raise ValueError("O progresso deve estar entre 0 e 100.")
        with self._lock:
            current = self._jobs.get(analysis_id)
            if current is None:
                raise AnalysisJobNotFoundError(
                    f"A análise {analysis_id!r} não foi encontrada."
                )
            if status not in self._ALLOWED_TRANSITIONS[current.status]:
                raise ValueError(
                    f"Transição inválida: {current.status.value} -> {status.value}."
                )
            if progress < current.progress and not (
                current.status in {AnalysisJobStatus.SUCCEEDED, AnalysisJobStatus.FAILED}
                and status is AnalysisJobStatus.RESEARCHING
            ):
                raise ValueError("O progresso de uma análise não pode diminuir.")
            updated = replace(
                current,
                status=status,
                progress=progress,
                updated_at=self._now(),
                result=result if result is not None else current.result,
                error=error if error is not None else current.error,
                workflow=workflow if workflow is not None else current.workflow,
            )
            self._jobs[analysis_id] = updated
        return updated

    def update_result(self, analysis_id: str, result: Mapping[str, Any]) -> AnalysisJob:
        with self._lock:
            current = self._jobs.get(analysis_id)
            if current is None:
                raise AnalysisJobNotFoundError(
                    f"A análise {analysis_id!r} não foi encontrada."
                )
            if current.status is not AnalysisJobStatus.SUCCEEDED:
                raise ValueError("Somente análises concluídas podem ser atualizadas.")
            updated = replace(current, result=result, updated_at=self._now())
            self._jobs[analysis_id] = updated
        return updated

    def list_ids(self, status: AnalysisJobStatus) -> list[str]:
        with self._lock:
            return [job.analysis_id for job in self._jobs.values() if job.status is status]


class SQLiteAnalysisJobStore:
    """Store durável; permite retomar a seleção após reiniciar a aplicação."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    analysis_id TEXT PRIMARY KEY,
                    claim TEXT NOT NULL,
                    article_reference TEXT,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    workflow_json TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Fecha a conexão após cada operação, inclusive quando há exceção."""

        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def mark_interrupted_jobs_failed(self) -> int:
        """Finaliza jobs cujo executor desapareceu em uma reinicialização."""

        interrupted = (
            AnalysisJobStatus.QUEUED.value,
            AnalysisJobStatus.RUNNING.value,
            AnalysisJobStatus.RESEARCHING.value,
        )
        error = json.dumps(
            {
                "code": "APPLICATION_RESTARTED",
                "message": (
                    "A aplicação foi reiniciada durante o processamento. "
                    "Inicie a análise novamente."
                ),
            },
            ensure_ascii=False,
        )
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, progress = 100, updated_at = ?, error_json = ?
                WHERE status IN (?, ?, ?)
                """,
                (
                    AnalysisJobStatus.FAILED.value,
                    self._now(),
                    error,
                    *interrupted,
                ),
            )
        return max(0, cursor.rowcount)

    def healthcheck(self) -> None:
        """Confirma que o banco está acessível e com a tabela esperada."""

        with self._connection() as connection:
            connection.execute("SELECT 1 FROM analysis_jobs LIMIT 1").fetchone()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _loads(value: str | None) -> Mapping[str, Any] | None:
        return json.loads(value) if value else None

    @classmethod
    def _job_from_row(cls, row: sqlite3.Row) -> AnalysisJob:
        return AnalysisJob(
            analysis_id=row["analysis_id"],
            claim=row["claim"],
            article_reference=row["article_reference"],
            status=AnalysisJobStatus(row["status"]),
            progress=row["progress"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            result=cls._loads(row["result_json"]),
            error=cls._loads(row["error_json"]),
            workflow=cls._loads(row["workflow_json"]),
        )

    def create(self, analysis_input: AnalysisInput) -> AnalysisJob:
        timestamp = self._now()
        job = AnalysisJob(
            analysis_id=str(uuid4()),
            claim=analysis_input.claim,
            article_reference=analysis_input.article_reference,
            status=AnalysisJobStatus.QUEUED,
            progress=0,
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO analysis_jobs (
                    analysis_id, claim, article_reference, status, progress,
                    created_at, updated_at, result_json, error_json, workflow_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (
                    job.analysis_id,
                    job.claim,
                    job.article_reference,
                    job.status.value,
                    job.progress,
                    job.created_at,
                    job.updated_at,
                ),
            )
        return job

    def get(self, analysis_id: str) -> AnalysisJob:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            raise AnalysisJobNotFoundError(
                f"A análise {analysis_id!r} não foi encontrada."
            )
        return self._job_from_row(row)

    def transition(
        self,
        analysis_id: str,
        *,
        status: AnalysisJobStatus,
        progress: int,
        result: Mapping[str, Any] | None = None,
        error: Mapping[str, str] | None = None,
        workflow: Mapping[str, Any] | None = None,
    ) -> AnalysisJob:
        if not 0 <= progress <= 100:
            raise ValueError("O progresso deve estar entre 0 e 100.")
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
            if row is None:
                raise AnalysisJobNotFoundError(
                    f"A análise {analysis_id!r} não foi encontrada."
                )
            current = self._job_from_row(row)
            if status not in ALLOWED_JOB_TRANSITIONS[current.status]:
                raise ValueError(
                    f"Transição inválida: {current.status.value} -> {status.value}."
                )
            if progress < current.progress and not (
                current.status in {AnalysisJobStatus.SUCCEEDED, AnalysisJobStatus.FAILED}
                and status is AnalysisJobStatus.RESEARCHING
            ):
                raise ValueError("O progresso de uma análise não pode diminuir.")
            updated = replace(
                current,
                status=status,
                progress=progress,
                updated_at=self._now(),
                result=result if result is not None else current.result,
                error=error if error is not None else current.error,
                workflow=workflow if workflow is not None else current.workflow,
            )
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, progress = ?, updated_at = ?, result_json = ?,
                    error_json = ?, workflow_json = ?
                WHERE analysis_id = ?
                """,
                (
                    updated.status.value,
                    updated.progress,
                    updated.updated_at,
                    json.dumps(updated.result, ensure_ascii=False) if updated.result is not None else None,
                    json.dumps(updated.error, ensure_ascii=False) if updated.error is not None else None,
                    json.dumps(updated.workflow, ensure_ascii=False) if updated.workflow is not None else None,
                    updated.analysis_id,
                ),
            )
        return updated

    def update_result(self, analysis_id: str, result: Mapping[str, Any]) -> AnalysisJob:
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
            if row is None:
                raise AnalysisJobNotFoundError(
                    f"A análise {analysis_id!r} não foi encontrada."
                )
            current = self._job_from_row(row)
            if current.status is not AnalysisJobStatus.SUCCEEDED:
                raise ValueError("Somente análises concluídas podem ser atualizadas.")
            updated = replace(current, result=result, updated_at=self._now())
            connection.execute(
                "UPDATE analysis_jobs SET result_json = ?, updated_at = ? WHERE analysis_id = ?",
                (json.dumps(result, ensure_ascii=False), updated.updated_at, analysis_id),
            )
        return updated

    def list_ids(self, status: AnalysisJobStatus) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT analysis_id FROM analysis_jobs WHERE status = ? ORDER BY updated_at",
                (status.value,),
            ).fetchall()
        return [row["analysis_id"] for row in rows]


ResultSerializer = Callable[[Any], Mapping[str, Any]]


class AnalysisJobService:
    """Executa o pipeline fora da requisição e preserva seu estado consultável."""

    def __init__(
        self,
        runner: AnalysisRunner,
        *,
        store: AnalysisJobStore | None = None,
        executor: Executor | None = None,
        result_serializer: ResultSerializer | None = None,
        article_runner: ArticleAnalysisRunner | None = None,
        study_tools: StudyToolsRunner | None = None,
        max_workers: int = 2,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers deve ser maior que zero.")
        self.runner = runner
        self.store = store or InMemoryAnalysisJobStore()
        self._owns_executor = executor is None
        self.executor = executor or ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="fatofake-analysis",
        )
        self.result_serializer = result_serializer or serialize_multi_article_analysis
        self.article_runner = article_runner
        self.study_tools = study_tools
        self._result_lock = Lock()
        self.library = ArticleLibrary(getattr(self.store, "database_path", None))
        self.library.import_prepared_analyses()

    def submit(
        self,
        claim: str,
        article_reference: str | None = None,
    ) -> AnalysisJob:
        analysis_input = validate_analysis_input(claim, article_reference)
        job = self.store.create(analysis_input)
        log_event(
            logger,
            logging.INFO,
            "Análise enfileirada",
            event="analysis.job",
            stage="queue",
            status="queued",
            analysis_id=job.analysis_id,
            input_type="claim",
            claim_length=len(analysis_input.claim),
            has_article_reference=bool(analysis_input.article_reference),
        )
        try:
            self.executor.submit(self._run, job.analysis_id, analysis_input)
        except Exception:
            log_event(
                logger,
                logging.ERROR,
                "Falha ao agendar análise",
                exc_info=True,
                event="analysis.job",
                stage="queue",
                status="failed",
                analysis_id=job.analysis_id,
            )
            self.store.transition(
                job.analysis_id,
                status=AnalysisJobStatus.FAILED,
                progress=100,
                error={
                    "code": "SCHEDULING_FAILED",
                    "message": "Não foi possível agendar a análise.",
                },
            )
        return job

    def _run(self, analysis_id: str, analysis_input: AnalysisInput) -> None:
        with bind_log_context(analysis_id=analysis_id):
            self.store.transition(
                analysis_id,
                status=AnalysisJobStatus.RUNNING,
                progress=10,
            )
            log_event(
                logger,
                logging.INFO,
                "Análise iniciada",
                event="analysis.job",
                stage="pipeline",
                status="running",
                progress=10,
            )
            try:
                with logged_step(logger, "analysis_pipeline"):
                    analysis = self.runner.analyze(
                        analysis_input.claim,
                        analysis_input.article_reference,
                    )
                    result = self.result_serializer(analysis)
            except AnalysisServiceError as error:
                self.store.transition(
                    analysis_id,
                    status=AnalysisJobStatus.FAILED,
                    progress=100,
                    error={"code": "ANALYSIS_FAILED", "message": str(error)},
                )
                log_event(
                    logger,
                    logging.WARNING,
                    "Análise encerrada com falha conhecida",
                    event="analysis.job",
                    stage="pipeline",
                    status="failed",
                    progress=100,
                    error_type=type(error).__name__,
                )
                return
            except Exception as error:
                self.store.transition(
                    analysis_id,
                    status=AnalysisJobStatus.FAILED,
                    progress=100,
                    error={
                        "code": "INTERNAL_ANALYSIS_ERROR",
                        "message": "A análise falhou durante o processamento.",
                    },
                )
                log_event(
                    logger,
                    logging.ERROR,
                    "Análise encerrada com erro interno",
                    event="analysis.job",
                    stage="pipeline",
                    status="failed",
                    progress=100,
                    error_type=type(error).__name__,
                )
                return

            self.store.transition(
                analysis_id,
                status=AnalysisJobStatus.SUCCEEDED,
                progress=100,
                result=result,
            )
            log_event(
                logger,
                logging.INFO,
                "Análise concluída",
                event="analysis.job",
                stage="pipeline",
                status="succeeded",
                progress=100,
            )

    def submit_article(self, submission: ArticleSubmission, *, resolved_document=None) -> AnalysisJob:
        if self.article_runner is None:
            raise AnalysisServiceError("A análise de artigos não está configurada.")
        placeholder = AnalysisInput(
            claim="Alegação a extrair do artigo enviado",
            article_reference=submission.reference,
            reference_type=submission.reference_type or submission.mime_type,
        )
        job = self.store.create(placeholder)
        log_event(
            logger,
            logging.INFO,
            "Análise de artigo enfileirada",
            event="analysis.job",
            stage="queue",
            status="queued",
            analysis_id=job.analysis_id,
            input_type="article",
            source_type=submission.reference_type or submission.mime_type,
        )
        try:
            self.executor.submit(self._run_article, job.analysis_id, submission, resolved_document)
        except Exception:
            self.store.transition(
                job.analysis_id,
                status=AnalysisJobStatus.FAILED,
                progress=100,
                error={
                    "code": "SCHEDULING_FAILED",
                    "message": "Não foi possível agendar a análise do artigo.",
                },
            )
        return job

    def _run_article(self, analysis_id: str, submission: ArticleSubmission, resolved_document=None) -> None:
        with bind_log_context(analysis_id=analysis_id):
            self.store.transition(
                analysis_id,
                status=AnalysisJobStatus.RUNNING,
                progress=10,
            )
            log_event(
                logger,
                logging.INFO,
                "Análise de artigo iniciada",
                event="analysis.job",
                stage="article_pipeline",
                status="running",
                progress=10,
            )
            try:
                assert self.article_runner is not None
                with logged_step(logger, "article_analysis_pipeline"):
                    if not hasattr(self.article_runner, "prepare_article"):
                        result = self.article_runner.analyze_article(submission)
                        prepared = None
                    else:
                        prepared = (
                            self.article_runner.prepare_article(submission, resolved_document=resolved_document)
                            if resolved_document is not None else self.article_runner.prepare_article(submission)
                        )
                        result = self.article_runner.preparation_result(prepared)
                        if prepared.resolved and prepared.resolved.text.strip():
                            saved = self.library.save(prepared.submission, prepared.resolved, analysis_id=analysis_id)
                            result["library_article_id"] = saved["article_id"]
            except (AnalysisServiceError, ArticleIngestionError, GeminiAnalysisError) as error:
                self.store.transition(
                    analysis_id,
                    status=AnalysisJobStatus.FAILED,
                    progress=100,
                    error={"code": "ARTICLE_ANALYSIS_FAILED", "message": str(error)},
                )
                log_event(
                    logger,
                    logging.WARNING,
                    "Análise de artigo encerrada com falha conhecida",
                    event="analysis.job",
                    stage="article_pipeline",
                    status="failed",
                    progress=100,
                    error_type=type(error).__name__,
                )
                return
            except Exception as error:
                self.store.transition(
                    analysis_id,
                    status=AnalysisJobStatus.FAILED,
                    progress=100,
                    error={
                        "code": "INTERNAL_ANALYSIS_ERROR",
                        "message": "A análise do artigo falhou durante o processamento.",
                    },
                )
                log_event(
                    logger,
                    logging.ERROR,
                    "Análise de artigo encerrada com erro interno",
                    event="analysis.job",
                    stage="article_pipeline",
                    status="failed",
                    progress=100,
                    error_type=type(error).__name__,
                )
                return
            if prepared is not None:
                self.store.transition(
                    analysis_id,
                    status=AnalysisJobStatus.AWAITING_CLAIM_SELECTION,
                    progress=40,
                    result=result,
                    workflow=prepared.to_workflow_payload(),
                )
                log_event(
                    logger,
                    logging.INFO,
                    "Artigo preparado; aguardando seleção de alegações",
                    event="analysis.job",
                    stage="claim_selection",
                    status="awaiting_user",
                    progress=40,
                )
                return
            self.store.transition(
                analysis_id,
                status=AnalysisJobStatus.SUCCEEDED,
                progress=100,
                result=result,
            )
            log_event(
                logger,
                logging.INFO,
                "Análise de artigo concluída",
                event="analysis.job",
                stage="article_pipeline",
                status="succeeded",
                progress=100,
            )

    def select_article_claims(self, analysis_id, selections, depth="QUICK", comparison=None, source_base_url="http://localhost:5000"):
        with self._result_lock:
            return self._select_article_claims(analysis_id, selections, depth, comparison, source_base_url)

    def _select_article_claims(
        self,
        analysis_id: str,
        selections: Any,
        depth: Any = "QUICK",
        comparison=None,
        source_base_url="http://localhost:5000",
    ) -> AnalysisJob:
        if self.article_runner is None:
            raise AnalysisServiceError("A análise de artigos não está configurada.")
        job = self.store.get(analysis_id)
        if job.status not in {AnalysisJobStatus.AWAITING_CLAIM_SELECTION, AnalysisJobStatus.SUCCEEDED, AnalysisJobStatus.FAILED}:
            raise InputValidationError(
                "Esta análise não está aguardando a seleção de alegações."
            )
        if any((item.get("result") or {}).get("complementary", {}).get("status") == "RUNNING"
               for item in (job.result or {}).get("claim_analyses") or ()):
            raise InputValidationError("Aguarde a pesquisa complementar terminar antes de iniciar outra rodada.")
        if not isinstance(selections, list) or not selections:
            raise InputValidationError("Selecione ao menos uma alegação.")
        if len(selections) > 10:
            raise InputValidationError("Selecione no máximo 10 alegações.")
        if depth not in SEARCH_DEPTHS:
            raise InputValidationError("A profundidade deve ser QUICK ou DEEP.")
        if job.workflow is None:
            raise AnalysisServiceError("O snapshot preparado desta análise está ausente.")
        prepared = PreparedArticle.from_workflow_payload(job.workflow)
        originals = {
            claim.claim_id: claim
            for claim in getattr(self.article_runner, "_claims_for")(prepared.extracted)
        }
        selected: list[ExtractedClaim] = []
        custom: list[ExtractedClaim] = []
        seen: set[str] = set()
        for item in selections:
            if not isinstance(item, dict) or set(item) - {"claim_id", "text", "source"}:
                raise InputValidationError(
                    "Cada seleção deve conter claim_id e text; alegações próprias podem informar source=USER."
                )
            claim_id = item.get("claim_id")
            claim_text = item.get("text")
            if not isinstance(claim_id, str) or not claim_id or len(claim_id) > 80 or claim_id in seen:
                raise InputValidationError("A seleção contém uma alegação inválida ou repetida.")
            if item.get("source") not in {None, "USER"}:
                raise InputValidationError("A origem da alegação deve ser USER quando adicionada manualmente.")
            if claim_id not in originals and (item.get("source") != "USER" or not claim_id.startswith("user-")):
                raise InputValidationError("A seleção contém uma alegação inválida ou repetida.")
            if not isinstance(claim_text, str) or not 8 <= len(claim_text.strip()) <= 2000:
                raise InputValidationError(
                    "O texto editado de cada alegação deve ter entre 8 e 2.000 caracteres."
                )
            if claim_id not in originals:
                original = ExtractedClaim(claim_id, claim_text.strip(), claim_text.strip(), edited=True, user_supplied=True)
                originals[claim_id] = original
                custom.append(original)
            original = originals[claim_id]
            normalized = claim_text.strip()
            selected.append(
                replace(
                    original,
                    text=normalized,
                    search_query=(
                        original.search_query
                        if normalized == original.text
                        else normalized
                    ),
                    edited=normalized != original.text or original.user_supplied,
                )
            )
            seen.add(claim_id)
        if custom:
            prepared = replace(prepared, extracted=replace(prepared.extracted,
                claims=tuple(self.article_runner._claims_for(prepared.extracted)) + tuple(custom)))
        documents = self.comparison_documents(comparison, prepared, source_base_url) if comparison is not None else None
        snapshot = json.loads(json.dumps(job.result or self.article_runner.preparation_result(prepared)))
        previous = {item["claim_id"]: item for item in snapshot.get("claim_analyses") or ()}
        for claim in selected:
            previous[claim.claim_id] = {"claim_id": claim.claim_id, "claim": self.article_runner._claim_payload(claim)
                if hasattr(self.article_runner, "_claim_payload") else {"text": claim.text}, "status": "QUEUED"}
        snapshot["claim_analyses"] = list(previous.values())
        if custom:
            snapshot.setdefault("submitted_article", {})["claims"] = [
                ArticleFirstAnalysisRunner._claim_payload(claim) for claim in self.article_runner._claims_for(prepared.extracted)
            ]
        snapshot["comparison"] = {"mode": "MANUAL" if documents is not None else "AUTOMATIC",
                                   "article_ids": [key for key, _ in documents or ()]}
        researching = self.store.transition(
            analysis_id,
            status=AnalysisJobStatus.RESEARCHING,
            progress=45,
            result=snapshot,
            error={},
            workflow=prepared.to_workflow_payload(),
        )
        try:
            self.executor.submit(
                self._run_selected_claims,
                analysis_id,
                prepared,
                tuple(selected),
                depth,
                documents,
            )
        except Exception:
            self.store.transition(
                analysis_id,
                status=AnalysisJobStatus.FAILED,
                progress=100,
                error={
                    "code": "SCHEDULING_FAILED",
                    "message": "Não foi possível agendar a pesquisa das alegações.",
                },
            )
        return researching

    def _run_selected_claims(self, analysis_id, prepared, selected_claims, depth="QUICK", documents=None):
        with bind_log_context(analysis_id=analysis_id):
            snapshot = json.loads(json.dumps(self.store.get(analysis_id).result))
            for position, claim in enumerate(selected_claims):
                entries = snapshot["claim_analyses"]
                index = next(i for i, item in enumerate(entries) if item["claim_id"] == claim.claim_id)
                entries[index]["status"] = "RUNNING"
                progress = 45 + int(50 * position / len(selected_claims))
                self.store.transition(analysis_id, status=AnalysisJobStatus.RESEARCHING, progress=progress,
                                      result=json.loads(json.dumps(snapshot)))
                try:
                    options = {"depth": depth}
                    if documents is not None:
                        options["comparison_documents"] = documents
                    one = dict(self.article_runner.analyze_prepared(prepared, (claim,), **options))
                    completed = next(item for item in one["claim_analyses"] if item["claim_id"] == claim.claim_id)
                    completed.setdefault("status", "SUCCEEDED")
                    completed["comparison"] = dict(snapshot["comparison"])
                    entries[index] = completed
                    # Mantém dossiê, metadados e resultados das outras alegações.
                    for key, value in one.items():
                        if key != "claim_analyses":
                            snapshot[key] = value
                except Exception as error:
                    logger.exception("Falha na alegação %s", claim.claim_id)
                    message = str(error) if isinstance(error, (AnalysisServiceError, ArticleIngestionError, GeminiAnalysisError)) else "A comparação desta alegação falhou. Tente novamente."
                    entries[index] = {**entries[index], "status": "FAILED", "error": {"message": message}}
                self.store.transition(analysis_id, status=AnalysisJobStatus.RESEARCHING,
                    progress=45 + int(50 * (position + 1) / len(selected_claims)),
                    result=json.loads(json.dumps(snapshot)))
            snapshot.setdefault("reproducibility", {})["selected_claims"] = [item["claim_id"] for item in snapshot["claim_analyses"]]
            successful = any(item.get("status") == "SUCCEEDED" for item in snapshot["claim_analyses"])
            self.store.transition(analysis_id,
                status=AnalysisJobStatus.SUCCEEDED if successful else AnalysisJobStatus.FAILED,
                progress=100, result=snapshot,
                error={} if successful else {"code": "ARTICLE_ANALYSIS_FAILED", "message": "As alegações selecionadas falharam. Você pode tentar novamente."})

    def resolve_library_submission(self, submission):
        if self.article_runner is None:
            raise AnalysisServiceError("A leitura de artigos não está configurada.")
        resolver = getattr(self.article_runner, "reference_resolver", None)
        resolved = resolver.resolve(submission) if submission.reference and resolver else None
        if resolved is None and submission.mime_type == "application/pdf":
            parser = getattr(self.article_runner, "document_parser", None)
            if parser is None:
                raise AnalysisServiceError("A leitura de PDFs não está configurada.")
            try:
                parsed = parser.parse_pdf(submission.content)
            except DocumentParsingError as error:
                raise InputValidationError(str(error)) from error
            resolved = ResolvedArticleDocument(title=None, doi=None, text=parsed.text,
                parser_name=parsed.parser_name, page_count=parsed.page_count,
                pages=tuple(parsed.pages or ()), content_scope="LOCAL_PDF_FULL_TEXT")
        if resolved is None or not resolved.text.strip():
            raise InputValidationError("Não foi possível recuperar o texto. Use um artigo do PubMed ou envie o PDF.")
        return resolved

    def save_library_article(self, payload):
        if "analysis_id" in payload:
            job = self.store.get(payload["analysis_id"])
            if not job.workflow:
                raise InputValidationError("A análise não possui uma fonte preparada para guardar.")
            prepared = PreparedArticle.from_workflow_payload(job.workflow)
            return self.library.save(prepared.submission, prepared.resolved, analysis_id=job.analysis_id)
        submission = validate_article_submission(payload)
        return self.library.save(submission, self.resolve_library_submission(submission))

    def comparison_documents(self, comparison, prepared, source_base_url):
        if not isinstance(comparison, dict) or set(comparison) - {"mode", "article_ids", "references", "files"}:
            raise InputValidationError("Configuração de comparação inválida.")
        if comparison.get("mode", "AUTOMATIC") == "AUTOMATIC":
            if any(comparison.get(key) for key in ("article_ids", "references", "files")):
                raise InputValidationError("Selecione comparação manual para fornecer artigos.")
            return None
        if comparison.get("mode") != "MANUAL":
            raise InputValidationError("O modo deve ser AUTOMATIC ou MANUAL.")
        ids, references, files = (comparison.get(key) or [] for key in ("article_ids", "references", "files"))
        if any(not isinstance(values, list) for values in (ids, references, files)) or not 1 <= len(ids)+len(references)+len(files) <= 20:
            raise InputValidationError("Escolha de 1 a 20 artigos para comparar.")
        if any(not isinstance(value, str) for value in ids + references):
            raise InputValidationError("Identificadores e referências devem ser texto.")
        ids = list(ids)
        for reference in references:
            saved = self.save_library_article({"article_reference": reference})
            ids.append(saved["article_id"])
        for file in files:
            saved = self.save_library_article({"article_file": file})
            ids.append(saved["article_id"])
        documents = []
        for article_id in dict.fromkeys(ids):
            saved_submission, document = self.library.load(article_id)
            if document.title is None:
                document = replace(document, title=saved_submission.file_name or "Documento da biblioteca")
            target = prepared.resolved
            if target and (document.text == target.text or
                (document.pmid and document.pmid == target.pmid) or
                (document.doi and target.doi and document.doi.lower() == target.doi.lower())):
                raise InputValidationError("O artigo alvo não pode ser usado como referência contra si próprio.")
            document = replace(document, source_url=document.source_url or
                source_base_url.rstrip('/') + '/api/v1/library/articles/' + article_id)
            documents.append((article_id, document))
        return tuple(documents)

    def get(self, analysis_id: str) -> AnalysisJob:
        return self.store.get(analysis_id)

    def _completed_claim(
        self, analysis_id: str, claim_id: str
    ) -> tuple[AnalysisJob, dict[str, Any], int]:
        if self.study_tools is None:
            raise AnalysisServiceError("As ferramentas de estudo não estão configuradas.")
        job = self.store.get(analysis_id)
        if job.status is not AnalysisJobStatus.SUCCEEDED or job.result is None:
            raise InputValidationError("A análise ainda não terminou.")
        result = json.loads(json.dumps(job.result))
        for index, item in enumerate(result.get("claim_analyses") or ()):
            if item.get("claim_id") == claim_id:
                return job, result, index
        raise InputValidationError("A alegação indicada não pertence a esta análise.")

    @staticmethod
    def _store_claim_result(
        result: dict[str, Any], index: int, claim_result: Mapping[str, Any]
    ) -> None:
        result["claim_analyses"][index]["result"] = dict(claim_result)
        if index == 0:
            # O topo do resultado espelha a primeira alegação por compatibilidade.
            for key in (
                "articles",
                "weighted_evidence",
                "user_summary",
                "updates",
                "complementary",
                "trial_registry",
                "search",
            ):
                if key in claim_result:
                    result[key] = claim_result[key]

    def attach_study_full_text(
        self,
        analysis_id: str,
        claim_id: str,
        study_key: Any,
        file_payload: Any,
    ) -> AnalysisJob:
        if not isinstance(study_key, str) or not study_key.strip():
            raise InputValidationError("Informe o estudo que receberá o PDF.")
        submission = validate_article_submission({"article_file": file_payload})
        if submission.mime_type != "application/pdf" or submission.content is None:
            raise InputValidationError("Envie o texto completo do estudo em PDF.")
        with self._result_lock:
            _job, result, index = self._completed_claim(analysis_id, claim_id)
            analysis = result["claim_analyses"][index]
            claim = analysis.get("claim") or {}
            with bind_log_context(analysis_id=analysis_id):
                updated = self.study_tools.reassess_with_full_text(
                    analysis["result"],
                    claim_text=claim.get("text") or analysis.get("claim_id"),
                    claim_profile=claim.get("profile"),
                    study_key=study_key.strip(),
                    pdf_bytes=submission.content,
                )
            self._store_claim_result(result, index, updated)
            return self.store.update_result(analysis_id, result)

    def check_new_studies(self, analysis_id: str, claim_id: str | None = None) -> AnalysisJob:
        with self._result_lock:
            job = self.store.get(analysis_id)
            if job.status is not AnalysisJobStatus.SUCCEEDED or job.result is None:
                raise InputValidationError("A análise ainda não terminou.")
            claim_ids = [
                item.get("claim_id")
                for item in job.result.get("claim_analyses") or ()
                if claim_id in (None, item.get("claim_id"))
            ]
            if not claim_ids:
                raise InputValidationError("A alegação indicada não pertence a esta análise.")
            result = json.loads(json.dumps(job.result))
            for current_id in claim_ids:
                _job, _result, index = self._completed_claim(analysis_id, current_id)
                claim_result = dict(result["claim_analyses"][index]["result"])
                with bind_log_context(analysis_id=analysis_id):
                    claim_result["updates"] = dict(
                        self.study_tools.find_new_studies(claim_result)
                    )
                self._store_claim_result(result, index, claim_result)
            return self.store.update_result(analysis_id, result)

    def start_complementary_search(self, analysis_id: str, claim_id: str) -> AnalysisJob:
        with self._result_lock:
            _job, result, index = self._completed_claim(analysis_id, claim_id)
            claim_result = dict(result["claim_analyses"][index]["result"])
            if (claim_result.get("complementary") or {}).get("status") == "RUNNING":
                raise InputValidationError("A pesquisa complementar desta alegação já está em andamento.")
            claim_result["complementary"] = {
                "status": "RUNNING",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            self._store_claim_result(result, index, claim_result)
            job = self.store.update_result(analysis_id, result)
        self.executor.submit(self._run_complementary, analysis_id, claim_id)
        return job

    def _run_complementary(self, analysis_id: str, claim_id: str) -> None:
        with bind_log_context(analysis_id=analysis_id):
            job, result, index = self._completed_claim(analysis_id, claim_id)
            analysis = result["claim_analyses"][index]
            claim = analysis.get("claim") or {}
            submitted_doi = (result.get("submitted_article") or {}).get("doi")
            try:
                with logged_step(logger, "complementary_search", claim_id=claim_id):
                    updated = dict(
                        self.study_tools.complementary_search(
                            analysis["result"],
                            claim_text=claim.get("text") or claim_id,
                            claim_profile=claim.get("profile"),
                            excluded_dois=(submitted_doi,) if submitted_doi else (),
                        )
                    )
            except Exception as error:
                logger.exception("Pesquisa complementar falhou")
                updated = dict(analysis["result"])
                updated["complementary"] = {
                    "status": "FAILED",
                    "message": (
                        str(error)
                        if isinstance(error, (AnalysisServiceError, GeminiAnalysisError))
                        else "A pesquisa complementar falhou durante o processamento."
                    ),
                }
            with self._result_lock:
                # Relê o job: outra ação pode ter alterado o resultado nesse meio-tempo.
                _job, latest, latest_index = self._completed_claim(analysis_id, claim_id)
                self._store_claim_result(latest, latest_index, updated)
                self.store.update_result(analysis_id, latest)

    def source_preview(self, analysis_id: str) -> dict[str, Any]:
        job = self.store.get(analysis_id)
        workflow = job.workflow or {}
        resolved = workflow.get("resolved") or {}
        submission = workflow.get("submission") or {}
        extracted = workflow.get("extracted") or {}
        return {
            "title": resolved.get("title") or extracted.get("title"),
            "doi": resolved.get("doi") or extracted.get("doi"),
            "source": submission.get("reference") or submission.get("file_name"),
            "source_url": resolved.get("source_url"),
            "content_scope": resolved.get("content_scope") or "URL_CONTEXT_UNVERIFIED",
            "parser": resolved.get("parser_name"),
            "authors": resolved.get("authors") or [],
            "journal": resolved.get("journal"),
            "publication_date": resolved.get("publication_date"),
            "pages": resolved.get("pages") or [],
            "sections": [
                {"title": item[0], "text": item[1]} for item in resolved.get("sections") or []
            ],
            "text": resolved.get("text") or "",
            "claims": [
                {"claim_id": item.get("claim_id"), "text": item.get("text"),
                 "quote": item.get("quote"), "page": item.get("page"), "section": item.get("section")}
                for item in extracted.get("claims") or []
            ],
        }

    def set_watch(self, analysis_id: str, enabled: Any) -> AnalysisJob:
        if not isinstance(enabled, bool):
            raise InputValidationError("Informe enabled como verdadeiro ou falso.")
        with self._result_lock:
            job = self.store.get(analysis_id)
            if job.status is not AnalysisJobStatus.SUCCEEDED or job.result is None:
                raise InputValidationError("A análise ainda não terminou.")
            result = dict(job.result)
            result["watch"] = {
                "enabled": enabled,
                "changed_at": datetime.now(timezone.utc).isoformat(),
            }
            return self.store.update_result(analysis_id, result)

    def run_watch_cycle(self) -> int:
        """Verifica novos estudos para análises acompanhadas; retorna quantas."""

        if self.study_tools is None:
            return 0
        checked = 0
        for analysis_id in self.store.list_ids(AnalysisJobStatus.SUCCEEDED):
            job = self.store.get(analysis_id)
            if not ((job.result or {}).get("watch") or {}).get("enabled"):
                continue
            try:
                self.check_new_studies(analysis_id)
                checked += 1
            except Exception:
                logger.exception("Falha ao verificar novos estudos de %s", analysis_id)
        return checked

    def close(self, *, wait: bool = True) -> None:
        if self._owns_executor:
            self.executor.shutdown(wait=wait)
        if wait:
            self.library.close()
            vector_store = getattr(self.runner, "vector_store", None)
            close_vector_store = getattr(vector_store, "close", None)
            if callable(close_vector_store):
                close_vector_store()

    def readiness(self) -> dict[str, str]:
        """Verifica dependências locais sem consumir PubMed ou Gemini."""

        database = "ok"
        try:
            check = getattr(self.store, "healthcheck", None)
            if callable(check):
                check()
            else:
                self.store.list_ids(AnalysisJobStatus.QUEUED)
        except Exception:
            database = "error"
        executor = "ok" if not getattr(self.executor, "_shutdown", False) else "error"
        payload = {
            "status": "ok" if database == executor == "ok" else "degraded",
            "database": database,
            "executor": executor,
        }
        from .retrieval_backend import RetrievalSettings
        settings = getattr(self.runner, "retrieval_settings", None)
        if isinstance(settings, RetrievalSettings) and settings.backend == "qdrant":
            try:
                self.runner.vector_store.health_check()
                payload["vector_store"] = "ok"
            except Exception:
                if settings.failure_mode == "bm25":
                    payload["vector_store"] = "unavailable_explicit_bm25"
                else:
                    payload["vector_store"] = "error"
                    payload["status"] = "degraded"
        return payload


def _serialize_assessment(assessment: Any) -> dict[str, Any]:
    evidence = assessment.evidence
    return {
        "pair_id": assessment.pair_id,
        "relation": assessment.relation.value,
        "model_relation": assessment.model_relation.value,
        "confidence": assessment.confidence,
        "margin": assessment.margin,
        "probabilities": {
            "support": assessment.probabilities.support,
            "contradiction": assessment.probabilities.contradiction,
            "neutral": assessment.probabilities.neutral,
        },
        "rationale": assessment.rationale,
        "model_name": assessment.model_name,
        "evidence": {
            "statement_id": evidence.statement_id,
            "text": evidence.text,
            "section": evidence.section,
            "pmid": evidence.pmid,
            "pmcid": evidence.pmcid,
            "doi": evidence.doi,
            "source_url": evidence.source_url,
        },
    }


def serialize_multi_article_analysis(
    analysis: MultiArticleAnalysis,
) -> dict[str, Any]:
    """Converte o resultado científico em um contrato JSON explícito."""

    search_result = analysis.search_result
    search_payload = {
        "queries": list(analysis.search_plan.queries),
        "query_results": [
            {
                "query": item.query,
                "total_matches": item.total_matches,
                **({"source": item.source} if hasattr(item, "source") else {}),
                **(
                    {"retrieved_count": item.retrieved_count}
                    if hasattr(item, "retrieved_count")
                    else {}
                ),
            }
            for item in search_result.query_results
        ],
        "candidate_count": len(search_result.publications),
    }
    if hasattr(search_result, "works"):
        search_payload.update(
            {
                "unique_work_count": len(search_result.works),
                "unresolved_work_count": len(search_result.unresolved_works),
                "source_failure_count": len(search_result.failures),
            }
        )

    return {
        "input": {
            "claim": analysis.analysis_input.claim,
            "article_reference": analysis.analysis_input.article_reference,
            "reference_type": analysis.analysis_input.reference_type,
        },
        "search": search_payload,
        "articles": [
            {
                "pmid": item.publication.pmid,
                "title": item.publication.title,
                "authors": list(item.publication.authors),
                "journal": item.publication.journal,
                "publication_date": item.publication.publication_date,
                "doi": item.publication.doi,
                "url": item.publication.url,
                "access_level": item.content.access_level,
                "pmcid": item.content.pmcid,
                "pmc_url": item.content.pmc_url,
                "quality": {
                    "study_design": item.quality_report.study_design.value,
                    "level": item.quality_report.quality_level.value,
                    "is_retracted": item.quality_report.is_retracted,
                    "rationale": item.quality_report.rationale,
                    "checks": [
                        {
                            "name": check.name,
                            "status": check.status.value,
                            "summary": check.summary,
                            "source_url": check.source_url,
                        }
                        for check in item.quality_report.checks
                    ],
                    "datasets": [
                        {
                            "doi": dataset.doi,
                            "title": dataset.title,
                            "relation_type": dataset.relation_type,
                            "url": dataset.url,
                        }
                        for dataset in item.quality_report.datasets
                    ],
                    "trial_registrations": [
                        {
                            "nct_id": trial.nct_id,
                            "overall_status": trial.overall_status,
                            "has_results": trial.has_results,
                            "url": trial.url,
                        }
                        for trial in item.quality_report.trial_registrations
                    ],
                },
                "assessments": [
                    _serialize_assessment(assessment)
                    for assessment in item.assessments
                ],
            }
            for item in analysis.articles
        ],
        "failures": [
            {
                "pmid": failure.pmid,
                "title": failure.title,
                "stage": failure.stage,
                "reason": failure.reason,
            }
            for failure in analysis.failures
        ],
        "synthesis": {
            "direction": analysis.synthesis.direction.value,
            "strength": analysis.synthesis.strength.value,
            "article_count": analysis.synthesis.article_count,
            "usable_article_count": sum(
                article.uncertain_count < article.assessment_count
                for article in analysis.synthesis.articles
            ),
            "has_conflict": analysis.synthesis.has_conflict,
            "probabilities": {
                "support": analysis.synthesis.support_probability,
                "contradiction": analysis.synthesis.contradiction_probability,
                "neutral": analysis.synthesis.neutral_probability,
            },
            "rationale": analysis.synthesis.rationale,
            "articles": [
                {
                    "pmid": article.pmid,
                    "direction": article.direction.value,
                    "assessment_count": article.assessment_count,
                    "usable_assessment_count": (
                        article.assessment_count - article.uncertain_count
                    ),
                    "uncertain_count": article.uncertain_count,
                    "has_internal_conflict": article.has_internal_conflict,
                    "quality_level": article.quality.level.value,
                }
                for article in analysis.synthesis.articles
            ],
        },
        "report": {
            "conclusion": analysis.report.conclusion.value,
            "headline": analysis.report.headline,
            "summary": analysis.report.summary,
            "methodology": [
                {
                    "pmid": item.pmid,
                    "instrument": item.instrument,
                    "confidence": item.confidence,
                    "quality_level": item.quality_level.value,
                    "critical_flaws": list(item.critical_flaws),
                    "single_reviewer": item.single_reviewer,
                    "rationale": item.rationale,
                    "applicability_note": item.applicability_note,
                    "source_url": item.source_url,
                }
                for item in analysis.report.methodology
            ],
            "limitations": list(analysis.report.limitations),
            "sources": [
                {
                    "label": source.label,
                    "url": source.url,
                    "pmid": source.pmid,
                }
                for source in analysis.report.sources
            ],
        },
        "verification": build_analysis_cards(analysis),
    }


def serialize_analysis_job(job: AnalysisJob) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "analysis_id": job.analysis_id,
        "status": job.status.value,
        "progress": job.progress,
        "claim": job.claim,
        "article_reference": job.article_reference,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }
    if job.result is not None:
        payload["result"] = job.result
    if job.error is not None:
        payload["error"] = dict(job.error)
    return payload


def _error_response(code: str, message: str, status_code: int):
    return jsonify({"error": {"code": code, "message": message}}), status_code


def create_app(
    job_service: AnalysisJobService,
    *,
    mode_label: str = "PROTÓTIPO LOCAL — resultados dependem do backend configurado",
    article_search: PubMedTopicSearch | None = None,
    topic_clusterer: Any = None,
    reference_comparer: Any = None,
    structured_search: Callable[..., Mapping[str, Any]] | None = None,
) -> Flask:
    """Cria a aplicação sem inicializar modelos ou serviços externos no import."""

    app = Flask(__name__)
    # Um arquivo de 25 MiB cresce ~33% em Base64; a margem cobre o envelope JSON.
    app.config["MAX_CONTENT_LENGTH"] = 36 * 1024 * 1024
    register_web_ui(app, mode_label=mode_label)

    @app.before_request
    def log_request_started():
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        g.fatofake_request_started = perf_counter()
        g.fatofake_request_id = request_id
        g.fatofake_request_context = bind_log_context(request_id=request_id)
        g.fatofake_request_context.__enter__()
        log_event(
            logger,
            logging.INFO,
            "Requisição recebida",
            event="http.request",
            stage="request",
            status="started",
            method=request.method,
            path=request.path,
        )

    @app.after_request
    def log_request_completed(response):
        started = getattr(g, "fatofake_request_started", perf_counter())
        log_event(
            logger,
            logging.INFO if response.status_code < 500 else logging.ERROR,
            "Requisição concluída",
            event="http.request",
            stage="request",
            status="completed" if response.status_code < 400 else "failed",
            method=request.method,
            path=request.path,
            status_code=response.status_code,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        response.headers["X-Request-ID"] = g.fatofake_request_id
        context = getattr(g, "fatofake_request_context", None)
        if context is not None:
            context.__exit__(None, None, None)
        return response

    @app.get("/api/v1/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/v1/ready")
    def readiness():
        payload = job_service.readiness()
        return jsonify(payload), (200 if payload["status"] == "ok" else 503)

    @app.get("/api/v1/library/articles")
    def list_library_articles():
        try:
            return jsonify({"articles": job_service.library.list(request.args.get("q", ""))})
        except InputValidationError as error:
            return _error_response("INVALID_INPUT", str(error), 422)

    @app.post("/api/v1/library/articles")
    def save_library_article():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) - {"analysis_id", "article_reference", "article_file"}:
            return _error_response("INVALID_INPUT", "Envie analysis_id ou uma referência/arquivo.", 422)
        if "analysis_id" in payload and (len(payload) != 1 or not isinstance(payload["analysis_id"], str)):
            return _error_response("INVALID_INPUT", "Envie somente analysis_id.", 422)
        try:
            return jsonify(job_service.save_library_article(payload)), 201
        except AnalysisJobNotFoundError:
            return _error_response("ANALYSIS_NOT_FOUND", "Análise não encontrada.", 404)
        except (InputValidationError, ArticleIngestionError) as error:
            return _error_response("INVALID_INPUT", str(error), 422)
        except (AnalysisServiceError, PubMedError) as error:
            return _error_response("LIBRARY_UNAVAILABLE", str(error), 503)

    @app.get("/api/v1/library/articles/<article_id>")
    def get_library_article(article_id):
        try:
            return jsonify(job_service.library.get(article_id))
        except InputValidationError as error:
            return _error_response("ARTICLE_NOT_FOUND", str(error), 404)

    @app.get("/api/v1/library/articles/<article_id>/file")
    def download_library_file(article_id):
        try:
            content, metadata = job_service.library.original_file(article_id)
            return send_file(BytesIO(content), mimetype=metadata.get("mime_type") or "application/octet-stream",
                             as_attachment=True, download_name=secure_filename(metadata.get("file_name") or "document.pdf"))
        except InputValidationError as error:
            return _error_response("FILE_NOT_FOUND", str(error), 404)

    @app.patch("/api/v1/library/articles/<article_id>")
    def annotate_library_article(article_id):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"notes", "tags"}:
            return _error_response("INVALID_INPUT", "Envie notes e tags.", 422)
        try:
            return jsonify(job_service.library.annotate(article_id, payload["notes"], payload["tags"]))
        except InputValidationError as error:
            return _error_response("INVALID_INPUT", str(error), 422)

    @app.post("/api/v1/library/articles/<article_id>/analyses")
    def analyze_library_article(article_id):
        try:
            submission, document = job_service.library.load(article_id)
            job = job_service.submit_article(submission, resolved_document=document)
            return jsonify({"analysis_id": job.analysis_id, "status_url": url_for("get_analysis", analysis_id=job.analysis_id)}), 202
        except InputValidationError as error:
            return _error_response("ARTICLE_NOT_FOUND", str(error), 404)
        except AnalysisServiceError as error:
            return _error_response("ARTICLE_ANALYSIS_UNAVAILABLE", str(error), 503)

    @app.post("/api/v1/pubmed-search")
    def search_pubmed_topics():
        if article_search is None:
            return _error_response("SEARCH_UNAVAILABLE", "Busca temática indisponível.", 503)
        if not request.is_json:
            return _error_response("UNSUPPORTED_MEDIA_TYPE", "Envie o corpo como application/json.", 415)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error_response("INVALID_JSON", "O JSON enviado é inválido.", 400)
        try:
            return jsonify(article_search.search(
                payload.get("topic"),
                article_type=payload.get("article_type", "ALL"),
                availability=payload.get("availability", "ALL"),
                indexing=payload.get("indexing", "MEDLINE"),
                language=payload.get("language", "ALL"),
                page=payload.get("page", 1),
                page_size=payload.get("page_size", 20),
                prepared_query=payload.get("prepared_query"),
            ))
        except InputValidationError as error:
            return _error_response("INVALID_INPUT", str(error), 400)
        except PubMedError:
            return _error_response("PUBMED_UNAVAILABLE", "Não foi possível consultar o PubMed. Tente novamente em instantes.", 502)

    @app.post("/api/v1/analyses/<analysis_id>/references")
    def compare_analysis_references(analysis_id):
        from .reference_comparison import analysis_articles
        if reference_comparer is None:
            return _error_response("REFERENCES_UNAVAILABLE", "Comparação de referências indisponível.", 503)
        if not request.is_json:
            return _error_response("UNSUPPORTED_MEDIA_TYPE", "Envie JSON.", 415)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("refresh", False), bool):
            return _error_response("INVALID_INPUT", "JSON inválido.", 400)
        claim_id = payload.get("claim_id")
        if claim_id is not None and not isinstance(claim_id, str):
            return _error_response("INVALID_INPUT", "claim_id deve ser texto.", 400)
        def selected(root):
            claims = root.get("claim_analyses") or []
            if claims:
                matches = [item for item in claims if item.get("claim_id") == claim_id] if claim_id else claims if len(claims) == 1 else []
                if len(matches) != 1 or matches[0].get("status") != "SUCCEEDED":
                    raise InputValidationError("Selecione uma alegação com pesquisa concluída.")
                return matches[0].get("result") or {}
            if claim_id:
                raise InputValidationError("A alegação não pertence a esta análise.")
            return root
        try:
            job = job_service.get(analysis_id)
            if job.status != AnalysisJobStatus.SUCCEEDED:
                return _error_response("ANALYSIS_NOT_READY", "Conclua a pesquisa antes de comparar referências.", 409)
            root = job.result or {}
            result = selected(root)
            articles = analysis_articles(result, root.get("submitted_article"))
            if not articles:
                raise InputValidationError("Esta análise não possui artigos para comparar.")
            fingerprint = reference_comparer.fingerprint(articles)
            cached = result.get("reference_comparison")
            if cached and cached.get("fingerprint") == fingerprint and not payload.get("refresh", False):
                return jsonify({**cached, "cache_hit": True})
            report = reference_comparer.compare(articles)
            latest = job_service.get(analysis_id)
            if latest.status != AnalysisJobStatus.SUCCEEDED:
                return _error_response("ANALYSIS_CHANGED", "A análise mudou durante a consulta. Tente novamente.", 409)
            updated = deepcopy(latest.result or {})
            target = selected(updated)
            if reference_comparer.fingerprint(analysis_articles(target, updated.get("submitted_article"))) != fingerprint:
                return _error_response("ANALYSIS_CHANGED", "Os artigos mudaram durante a consulta. Tente novamente.", 409)
            target["reference_comparison"] = report
            job_service.store.update_result(analysis_id, updated)
            return jsonify({**report, "cache_hit": False})
        except AnalysisJobNotFoundError:
            return _error_response("ANALYSIS_NOT_FOUND", "Análise não encontrada.", 404)
        except InputValidationError as error:
            return _error_response("INVALID_INPUT", str(error), 400)

    @app.post("/api/v1/pubmed-clusters")
    def cluster_pubmed_results():
        if topic_clusterer is None:
            return _error_response("CLUSTERING_UNAVAILABLE", "Agrupamento de temas indisponível.", 503)
        payload = request.get_json(silent=True)
        if not request.is_json:
            return _error_response("UNSUPPORTED_MEDIA_TYPE", "Envie JSON para agrupar os artigos.", 415)
        if not isinstance(payload, dict):
            return _error_response("INVALID_JSON", "O JSON enviado é inválido.", 400)
        try:
            return jsonify(topic_clusterer.cluster(payload.get("articles")))
        except InputValidationError as error:
            return _error_response("INVALID_INPUT", str(error), 400)
        except TopicClusteringError as error:
            return _error_response("CLUSTERING_UNAVAILABLE", str(error), 503)

    @app.post("/api/v1/structured-search")
    def search_structured_sources():
        if structured_search is None:
            return _error_response("SEARCH_UNAVAILABLE", "Busca estruturada indisponível.", 503)
        if not request.is_json:
            return _error_response("UNSUPPORTED_MEDIA_TYPE", "Envie o corpo como application/json.", 415)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error_response("INVALID_JSON", "O JSON enviado é inválido.", 400)
        try:
            claim = payload.get("claim")
            limit = payload.get("limit", 5)
            if not isinstance(claim, str) or not claim.strip():
                raise InputValidationError("A alegação deve ser um texto não vazio.")
            if not isinstance(limit, int) or isinstance(limit, bool):
                raise InputValidationError("limit deve ser um inteiro.")
            return jsonify(structured_search(claim, limit=limit))
        except (InputValidationError, ValueError) as error:
            return _error_response("INVALID_INPUT", str(error), 422)
        except StructuredSourceError as error:
            logger.exception("Falha na busca estruturada")
            return _error_response("STRUCTURED_SEARCH_FAILED", str(error), 502)

    @app.post("/api/v1/analyses")
    def create_analysis():
        if not request.is_json:
            return _error_response(
                "UNSUPPORTED_MEDIA_TYPE",
                "Envie o corpo como application/json.",
                415,
            )
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error_response("INVALID_JSON", "O JSON enviado é inválido.", 400)
        unknown_fields = set(payload) - {"claim", "article_reference"}
        if unknown_fields:
            fields = ", ".join(sorted(unknown_fields))
            return _error_response(
                "UNKNOWN_FIELDS",
                f"Campos não reconhecidos: {fields}.",
                400,
            )
        article_reference = payload.get("article_reference")
        if article_reference is not None and not isinstance(article_reference, str):
            return _error_response(
                "INVALID_INPUT",
                "A referência do artigo deve ser texto ou nula.",
                422,
            )
        try:
            job = job_service.submit(payload.get("claim"), article_reference)
        except InputValidationError as error:
            return _error_response("INVALID_INPUT", str(error), 422)

        status_url = url_for("get_analysis", analysis_id=job.analysis_id)
        response = jsonify(
            {
                "analysis_id": job.analysis_id,
                "status": job.status.value,
                "progress": job.progress,
                "status_url": status_url,
            }
        )
        response.status_code = 202
        response.headers["Location"] = status_url
        return response

    @app.post("/api/v1/article-analyses")
    def create_article_analysis():
        if not request.is_json:
            return _error_response(
                "UNSUPPORTED_MEDIA_TYPE",
                "Envie o corpo como application/json.",
                415,
            )
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error_response("INVALID_JSON", "O JSON enviado é inválido.", 400)
        unknown_fields = set(payload) - {"article_reference", "article_file"}
        if unknown_fields:
            return _error_response(
                "UNKNOWN_FIELDS",
                "Campos não reconhecidos: " + ", ".join(sorted(unknown_fields)) + ".",
                400,
            )
        try:
            submission = validate_article_submission(payload)
            job = job_service.submit_article(submission)
        except InputValidationError as error:
            return _error_response("INVALID_INPUT", str(error), 422)
        except AnalysisServiceError as error:
            return _error_response("ARTICLE_ANALYSIS_UNAVAILABLE", str(error), 503)

        status_url = url_for("get_analysis", analysis_id=job.analysis_id)
        response = jsonify(
            {
                "analysis_id": job.analysis_id,
                "status": job.status.value,
                "progress": job.progress,
                "status_url": status_url,
            }
        )
        response.status_code = 202
        response.headers["Location"] = status_url
        return response

    @app.get("/api/v1/analyses/<analysis_id>")
    def get_analysis(analysis_id: str):
        try:
            job = job_service.get(analysis_id)
        except AnalysisJobNotFoundError:
            return _error_response(
                "ANALYSIS_NOT_FOUND",
                "A análise solicitada não foi encontrada.",
                404,
            )
        if request.args.get("view") == "status":
            # Polling: só estado e progresso; o resultado completo pesa megabytes.
            payload = {
                key: value
                for key, value in serialize_analysis_job(job).items()
                if key != "result"
            }
            payload["claim_progress"] = [
                {"claim_id": item.get("claim_id"), "text": (item.get("claim") or {}).get("text"),
                 "status": item.get("status"), "error": item.get("error")}
                for item in (job.result or {}).get("claim_analyses") or ()
            ]
            response = jsonify(payload)
            if job.status in {
                AnalysisJobStatus.QUEUED,
                AnalysisJobStatus.RUNNING,
                AnalysisJobStatus.RESEARCHING,
            }:
                response.headers["Retry-After"] = "2"
            return response
        payload = serialize_analysis_job(job)
        if job.status is AnalysisJobStatus.AWAITING_CLAIM_SELECTION:
            payload["claim_selection_url"] = url_for(
                "select_article_claims",
                analysis_id=analysis_id,
            )
        response = jsonify(payload)
        if job.status in {
            AnalysisJobStatus.QUEUED,
            AnalysisJobStatus.RUNNING,
            AnalysisJobStatus.RESEARCHING,
        }:
            response.headers["Retry-After"] = "1"
        return response

    @app.get("/api/v1/analyses/<analysis_id>/report.md")
    def export_markdown_report(analysis_id: str):
        try:
            job = job_service.get(analysis_id)
        except AnalysisJobNotFoundError:
            return _error_response(
                "ANALYSIS_NOT_FOUND",
                "A análise solicitada não foi encontrada.",
                404,
            )
        if job.status is not AnalysisJobStatus.SUCCEEDED:
            return _error_response(
                "ANALYSIS_NOT_READY",
                "O relatório fica disponível quando a análise termina.",
                409,
            )
        return Response(
            render_markdown_report(serialize_analysis_job(job)),
            mimetype="text/markdown",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="fatofake-{analysis_id[:8]}.md"'
                )
            },
        )

    def _tool_call(action):
        try:
            job = action()
        except AnalysisJobNotFoundError:
            return _error_response(
                "ANALYSIS_NOT_FOUND",
                "A análise solicitada não foi encontrada.",
                404,
            )
        except InputValidationError as error:
            return _error_response("INVALID_INPUT", str(error), 422)
        except (AnalysisServiceError, GeminiAnalysisError) as error:
            return _error_response("STUDY_TOOL_UNAVAILABLE", str(error), 503)
        return jsonify(serialize_analysis_job(job))

    def _json_payload():
        if not request.is_json:
            return None
        payload = request.get_json(silent=True)
        return payload if isinstance(payload, dict) else None

    @app.post("/api/v1/analyses/<analysis_id>/claims/<claim_id>/studies/full-text")
    def attach_study_full_text(analysis_id: str, claim_id: str):
        payload = _json_payload()
        if payload is None or set(payload) != {"study_key", "article_file"}:
            return _error_response(
                "INVALID_INPUT",
                "Envie study_key e article_file em JSON.",
                422,
            )
        return _tool_call(
            lambda: job_service.attach_study_full_text(
                analysis_id, claim_id, payload["study_key"], payload["article_file"]
            )
        )

    @app.post("/api/v1/analyses/<analysis_id>/new-studies")
    def check_new_studies(analysis_id: str):
        payload = _json_payload() or {}
        claim_id = payload.get("claim_id")
        if claim_id is not None and not isinstance(claim_id, str):
            return _error_response("INVALID_INPUT", "claim_id deve ser texto.", 422)
        return _tool_call(lambda: job_service.check_new_studies(analysis_id, claim_id))

    @app.post("/api/v1/analyses/<analysis_id>/claims/<claim_id>/complementary-search")
    def start_complementary_search(analysis_id: str, claim_id: str):
        response = _tool_call(
            lambda: job_service.start_complementary_search(analysis_id, claim_id)
        )
        if isinstance(response, tuple):
            return response
        response.status_code = 202
        return response

    @app.get("/api/v1/analyses/<analysis_id>/source")
    def source_preview(analysis_id: str):
        try:
            preview = job_service.source_preview(analysis_id)
        except AnalysisJobNotFoundError:
            return _error_response(
                "ANALYSIS_NOT_FOUND",
                "A análise solicitada não foi encontrada.",
                404,
            )
        return jsonify(preview)

    @app.put("/api/v1/analyses/<analysis_id>/watch")
    def set_watch(analysis_id: str):
        payload = _json_payload()
        if payload is None or set(payload) != {"enabled"}:
            return _error_response("INVALID_INPUT", "Envie {\"enabled\": true|false}.", 422)
        return _tool_call(lambda: job_service.set_watch(analysis_id, payload["enabled"]))

    @app.post("/api/v1/article-analyses/<analysis_id>/claims")
    def select_article_claims(analysis_id: str):
        if not request.is_json:
            return _error_response(
                "UNSUPPORTED_MEDIA_TYPE",
                "Envie o corpo como application/json.",
                415,
            )
        payload = request.get_json(silent=True)
        if (
            not isinstance(payload, dict)
            or "claims" not in payload
            or set(payload) - {"claims", "depth", "comparison"}
        ):
            return _error_response(
                "INVALID_INPUT",
                "Envie um objeto com o campo claims (e, opcionalmente, depth).",
                422,
            )
        try:
            job = job_service.select_article_claims(
                analysis_id,
                payload.get("claims"),
                payload.get("depth", "QUICK"),
                payload.get("comparison"),
                request.url_root,
            )
        except AnalysisJobNotFoundError:
            return _error_response(
                "ANALYSIS_NOT_FOUND",
                "A análise solicitada não foi encontrada.",
                404,
            )
        except InputValidationError as error:
            return _error_response("INVALID_INPUT", str(error), 422)
        except AnalysisServiceError as error:
            return _error_response("ARTICLE_ANALYSIS_UNAVAILABLE", str(error), 503)
        status_url = url_for("get_analysis", analysis_id=analysis_id)
        response = jsonify(
            {
                "analysis_id": analysis_id,
                "status": job.status.value,
                "progress": job.progress,
                "status_url": status_url,
            }
        )
        response.status_code = 202
        response.headers["Location"] = status_url
        return response

    @app.errorhandler(413)
    def payload_too_large(_error):
        return _error_response(
            "PAYLOAD_TOO_LARGE",
            "O corpo da requisição excede o limite permitido.",
            413,
        )

    return app
