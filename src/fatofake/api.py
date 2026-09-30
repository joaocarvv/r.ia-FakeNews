"""API HTTP assíncrona para iniciar e consultar análises científicas."""

from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from flask import Flask, jsonify, request, url_for

from .analysis_service import AnalysisServiceError, MultiArticleAnalysis
from .input_validation import AnalysisInput, InputValidationError, validate_analysis_input


class AnalysisRunner(Protocol):
    """Contrato mínimo do pipeline chamado em segundo plano."""

    def analyze(
        self,
        claim: str,
        article_reference: str | None = None,
    ) -> MultiArticleAnalysis: ...


class AnalysisJobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
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


class AnalysisJobNotFoundError(LookupError):
    """O identificador não pertence a uma análise conhecida."""


class InMemoryAnalysisJobStore:
    """Armazena snapshots de trabalhos com transições protegidas por lock."""

    _ALLOWED_TRANSITIONS = {
        AnalysisJobStatus.QUEUED: {
            AnalysisJobStatus.RUNNING,
            AnalysisJobStatus.FAILED,
        },
        AnalysisJobStatus.RUNNING: {
            AnalysisJobStatus.SUCCEEDED,
            AnalysisJobStatus.FAILED,
        },
        AnalysisJobStatus.SUCCEEDED: set(),
        AnalysisJobStatus.FAILED: set(),
    }

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
            if progress < current.progress:
                raise ValueError("O progresso de uma análise não pode diminuir.")
            updated = replace(
                current,
                status=status,
                progress=progress,
                updated_at=self._now(),
                result=result,
                error=error,
            )
            self._jobs[analysis_id] = updated
        return updated


ResultSerializer = Callable[[Any], Mapping[str, Any]]


class AnalysisJobService:
    """Executa o pipeline fora da requisição e preserva seu estado consultável."""

    def __init__(
        self,
        runner: AnalysisRunner,
        *,
        store: InMemoryAnalysisJobStore | None = None,
        executor: Executor | None = None,
        result_serializer: ResultSerializer | None = None,
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

    def submit(
        self,
        claim: str,
        article_reference: str | None = None,
    ) -> AnalysisJob:
        analysis_input = validate_analysis_input(claim, article_reference)
        job = self.store.create(analysis_input)
        try:
            self.executor.submit(self._run, job.analysis_id, analysis_input)
        except Exception:
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
        self.store.transition(
            analysis_id,
            status=AnalysisJobStatus.RUNNING,
            progress=10,
        )
        try:
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
            return
        except Exception:
            self.store.transition(
                analysis_id,
                status=AnalysisJobStatus.FAILED,
                progress=100,
                error={
                    "code": "INTERNAL_ANALYSIS_ERROR",
                    "message": "A análise falhou durante o processamento.",
                },
            )
            return

        self.store.transition(
            analysis_id,
            status=AnalysisJobStatus.SUCCEEDED,
            progress=100,
            result=result,
        )

    def get(self, analysis_id: str) -> AnalysisJob:
        return self.store.get(analysis_id)

    def close(self, *, wait: bool = True) -> None:
        if self._owns_executor:
            self.executor.shutdown(wait=wait)


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

    return {
        "input": {
            "claim": analysis.analysis_input.claim,
            "article_reference": analysis.analysis_input.article_reference,
            "reference_type": analysis.analysis_input.reference_type,
        },
        "search": {
            "queries": list(analysis.search_plan.queries),
            "query_results": [
                {
                    "query": item.query,
                    "total_matches": item.total_matches,
                }
                for item in analysis.search_result.query_results
            ],
            "candidate_count": len(analysis.search_result.publications),
        },
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


def create_app(job_service: AnalysisJobService) -> Flask:
    """Cria a aplicação sem inicializar modelos ou serviços externos no import."""

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

    @app.get("/api/v1/health")
    def health():
        return jsonify({"status": "ok"})

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
        response = jsonify(serialize_analysis_job(job))
        if job.status in {AnalysisJobStatus.QUEUED, AnalysisJobStatus.RUNNING}:
            response.headers["Retry-After"] = "1"
        return response

    @app.errorhandler(413)
    def payload_too_large(_error):
        return _error_response(
            "PAYLOAD_TOO_LARGE",
            "O corpo da requisição excede o limite permitido.",
            413,
        )

    return app
