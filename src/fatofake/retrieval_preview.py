"""Aplicação de prévia que aceita alegações gerais e usa busca científica real."""

from __future__ import annotations

import json
import os
import re
import logging
from dataclasses import replace
from datetime import datetime, timezone
from time import perf_counter
import time
from threading import Lock, Thread
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .analysis_service import AnalysisServiceError
from .api import AnalysisJobService, SQLiteAnalysisJobStore, create_app
from .claim_structuring import GeminiClaimStructurer, boolean_queries, english_keywords
from .research_plan import SEARCH_DEPTHS
from .article_ingestion import (
    ArticleFirstAnalysisRunner,
    OpenAccessArticleResolver,
    GeminiArticleExtractor,
    PubMedReferenceResolver,
)
from .document_parsing import DocumentParsingError, LiteParseDocumentParser
from .chunking import ChunkingConfig, ChunkingError, chunk_article_content
from .crossref import CrossrefClient, CrossrefError
from .full_text_sources import FullTextCandidate, FullTextLead, FullTextLocator
from .trial_registry import ClinicalTrialsRegistry
from .evidence_table import synthesize_evidence
from .gemini_evidence import (
    EvidenceDocument,
    EvidencePassage,
    GeminiAnalysisError,
    GeminiEvidenceAnalyzer,
    GeminiEvidenceAssessment,
)
from .open_access_content import (
    Crawl4AiFetcher,
    OpenAccessContentClient,
    OpenAccessContentError,
)
from .federated_search import (
    EuropePmcSearchProvider,
    FederatedSearchEngine,
    FederatedSearchError,
    OpenAlexClient,
    OpenAlexGraphExplorer,
    OpenAlexSearchProvider,
    PubMedSearchProvider,
    ScieloSearchProvider,
    ScientificWork,
    SourceRank,
    deduplicate_works,
    normalize_doi,
    normalize_pmid,
)
from .input_validation import InputValidationError, validate_analysis_input
from .pmc import ArticleContent, ContentRetrievalError, ContentSection, PmcClient
from .pubmed import PubMedClient, PubMedError
from .topic_search import PubMedTopicSearch
from .quality_validation import classify_study_design
from .retrieval import Bm25Index, RetrievalError
from .result_presentation import build_user_summary
from .search_preparation import SearchPlan, prepare_search_plan
from .scientific_search import ClaimRelevanceReranker, expand_scientific_queries
from .verification_cards import (
    build_abstract_analysis_cards,
    build_unassessed_cards,
)
from .whole_article_analysis import GeminiWholeArticleAnalyzer
from .structured_logging import log_event, logged_step


logger = logging.getLogger(__name__)


RETRIEVAL_MODE_LABEL = "PUBMED/PMC — proveniência por trecho"
_STOPWORDS = {
    "a",
    "as",
    "ao",
    "aos",
    "de",
    "da",
    "das",
    "do",
    "dos",
    "e",
    "em",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "para",
    "por",
    "que",
    "um",
    "uma",
    "pode",
    "podem",
    "causa",
    "causar",
    "aumenta",
    "reduz",
    "risco",
}


class QueryTranslator(Protocol):
    def translate(self, text: str) -> str: ...


class MarianPortugueseEnglishTranslator:
    """Tradutor local e preguiçoso usado somente na preparação das consultas."""

    def __init__(
        self,
        model_name: str = "Helsinki-NLP/opus-mt-ROMANCE-en",
    ) -> None:
        self.model_name = model_name
        self._tokenizer = None
        self._model = None
        self._lock = Lock()

    def _load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
        self._model.eval()

    def translate(self, text: str) -> str:
        import torch

        with self._lock:
            self._load()
            inputs = self._tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=256,
            )
            with torch.inference_mode():
                generated = self._model.generate(
                    **inputs,
                    max_length=256,
                    num_beams=3,
                )
            translated = self._tokenizer.decode(
                generated[0],
                skip_special_tokens=True,
            )
        return " ".join(translated.split())


def _load_env(path: Path) -> None:
    """Carrega somente chaves ausentes, sem imprimir nem sobrescrever o ambiente."""

    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


class GenericHealthQueryPlanner:
    """Cria consultas genéricas transparentes, sem fingir tradução clínica."""

    def __init__(self, translator: QueryTranslator | None = None) -> None:
        self.translator = translator

    @staticmethod
    def _keywords(text: str) -> str:
        terms = [
            token
            for token in re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
            if len(token) >= 3 and token not in _STOPWORDS
        ]
        return " ".join(dict.fromkeys(terms))[:300]

    def generate_queries(self, claim: str) -> list[str]:
        compact = " ".join(claim.split())[:300]
        try:
            with logged_step(
                logger,
                "query_translation",
                enabled=self.translator is not None,
            ) as step:
                translated = (
                    self.translator.translate(compact) if self.translator else ""
                )
                step["translated"] = bool(translated)
        except Exception:
            # A indisponibilidade do modelo não deve impedir a busca. O texto
            # original ainda pode encontrar trabalhos indexados em português.
            translated = ""
        candidates = (
            translated,
            english_keywords(translated),
            compact,
            self._keywords(compact),
        )
        return list(
            dict.fromkeys(
                candidate for candidate in candidates if candidate.strip()
            )
        )[:3]


# Clinical Queries do PubMed (Haynes et al.): recortam pelo tipo de pergunta.
PUBMED_CLINICAL_FILTERS = {
    "THERAPEUTIC": "Therapy/Narrow[filter]",
    "PREVENTIVE": "Therapy/Narrow[filter]",
    "DIAGNOSTIC": "Diagnosis/Narrow[filter]",
    "PROGNOSTIC": "Prognosis/Narrow[filter]",
    "CAUSAL": "Etiology/Narrow[filter]",
    "ASSOCIATION": "Etiology/Narrow[filter]",
}


def _section_priority(title: str) -> int:
    normalized = title.casefold()
    if "result" in normalized:
        return 0
    if "conclu" in normalized:
        return 1
    if "discuss" in normalized:
        return 2
    return 3


def select_evidence_passages(
    content: ArticleContent,
    claim: str,
    key: str,
    *,
    max_passages: int = 4,
) -> tuple[EvidencePassage, ...]:
    """Trechos mais relevantes, priorizando Resultados e Conclusão."""

    with logged_step(logger, "article_chunk_retrieval", work=key) as step:
        chunks = chunk_article_content(
            content,
            ChunkingConfig(max_words=220, overlap_words=40),
        )
        ranked = list(Bm25Index(chunks).search(claim, top_k=8))
        step["chunk_count"] = len(chunks)
        step["ranked_count"] = len(ranked)
    ranked.sort(key=lambda item: (_section_priority(item.chunk.section), item.rank))
    selected = tuple(item.chunk for item in ranked[:max_passages]) or tuple(chunks[:2])
    return tuple(
        EvidencePassage(
            passage_id=chunk.chunk_id,
            text=chunk.text,
            section=chunk.section,
            page_number=chunk.page_number,
            source_url=chunk.source_url,
            content_scope=content.access_level,
        )
        for chunk in selected
    )


def work_key(work: Any) -> str | None:
    """Identificador estável do estudo: PMID ou, na falta dele, o DOI."""

    if work.pmid:
        return work.pmid
    return f"doi:{work.doi}" if work.doi else None


class RetrievalPreviewRunner:
    """Recupera fontes reais e compara somente trechos com proveniência."""

    def __init__(
        self,
        search_engine: FederatedSearchEngine,
        *,
        planner: GenericHealthQueryPlanner | None = None,
        abstract_client: PmcClient | None = None,
        evidence_analyzer: GeminiEvidenceAnalyzer | None = None,
        related_client: PubMedClient | None = None,
        openalex_graph: OpenAlexGraphExplorer | None = None,
        open_access_client: OpenAccessContentClient | None = None,
        crossref_client: CrossrefClient | None = None,
        full_text_locator: FullTextLocator | None = None,
        trial_registry: ClinicalTrialsRegistry | None = None,
        max_results_per_query: int = 5,
        max_analysis_articles: int = 5,
        pubmed_only: bool = False,
    ) -> None:
        if max_analysis_articles < 1:
            raise ValueError("max_analysis_articles deve ser maior que zero.")
        if pubmed_only and (
            any(provider.name != "PubMed" for provider in search_engine.providers)
            or any(item is not None for item in (openalex_graph, open_access_client, crossref_client, full_text_locator, trial_registry))
        ):
            raise ValueError("O modo PubMed-only não aceita fontes externas de literatura.")
        self.search_engine = search_engine
        self.planner = planner or GenericHealthQueryPlanner()
        self.abstract_client = abstract_client
        self.evidence_analyzer = evidence_analyzer
        self.related_client = related_client
        self.openalex_graph = openalex_graph
        self.open_access_client = open_access_client
        self.crossref_client = crossref_client
        self.full_text_locator = full_text_locator
        self.trial_registry = trial_registry
        self.max_results_per_query = max_results_per_query
        self.max_analysis_articles = max_analysis_articles
        self.pubmed_only = pubmed_only

    def _related_works(
        self, seed_pmids: Sequence[str]
    ) -> tuple[tuple[ScientificWork, ...], tuple[str, ...]]:
        if self.related_client is None or not seed_pmids:
            return (), ()
        works: list[ScientificWork] = []
        failures: list[str] = []
        for seed_pmid in dict.fromkeys(seed_pmids):
            try:
                identifiers = self.related_client.related_ids(
                    seed_pmid, max_results=self.max_results_per_query
                )
                publications = self.related_client.fetch_summaries(
                    identifiers,
                    {identifier: (f"related:{seed_pmid}",) for identifier in identifiers},
                )
            except PubMedError as error:
                failures.append(str(error))
                continue
            for rank, item in enumerate(publications, start=1):
                works.append(
                    ScientificWork(
                        title=item.title,
                        authors=item.authors,
                        journal=item.journal,
                        publication_date=item.publication_date,
                        doi=normalize_doi(item.doi),
                        pmid=normalize_pmid(item.pmid),
                        url=item.url,
                        matched_queries=(f"related:{seed_pmid}",),
                        sources=("PubMed relacionados",),
                        source_ids=(("PubMed relacionados", item.pmid),),
                        source_ranks=(
                            SourceRank(
                                "PubMed relacionados", f"related:{seed_pmid}", rank
                            ),
                        ),
                        publication_types=item.publication_types,
                    )
                )
        return tuple(works), tuple(failures)

    def _editorial_status(self, work: Any) -> tuple[str, str | None]:
        """Retratação, correção ou preprint segundo PubMed e Crossref."""

        types = " ".join(getattr(work, "publication_types", ()) or ()).casefold()
        if "retracted publication" in types:
            return "RETRACTED", "PubMed marca o registro como publicação retratada."
        status, detail = ("PREPRINT", "Tipo de publicação indica preprint.") if (
            "preprint" in types
        ) else ("PUBLISHED", None)
        if self.crossref_client is None or not work.doi:
            return status, detail
        try:
            crossref_work = self.crossref_client.fetch_work(work.doi)
        except CrossrefError:
            return status, detail
        update_types = {item.update_type for item in crossref_work.updates}
        if update_types & {"retraction", "withdrawal", "removal"}:
            return "RETRACTED", "O Crossref registra retratação ou remoção deste trabalho."
        if update_types & {"expression_of_concern", "expression-of-concern"}:
            return "EXPRESSION_OF_CONCERN", "O Crossref registra manifestação de preocupação."
        if str(crossref_work.work_type or "").casefold() in {"posted-content", "preprint"}:
            return "PREPRINT", "O Crossref classifica o registro como preprint (sem revisão por pares)."
        if update_types & {"correction", "erratum", "corrigendum"}:
            return "CORRECTED", "O Crossref registra correção publicada para este trabalho."
        return status, detail

    @staticmethod
    def _failure_reason(error: Exception) -> str:
        message = str(error)
        if "403" in message or "anti-bot" in message.casefold() or "401" in message:
            return "bloqueado pelo editor (acesso automatizado negado)"
        if "robots" in message.casefold() or "não permite" in message:
            return "o site não permite recuperação automatizada (robots.txt)"
        if "404" in message:
            return "link aberto não encontrado (404)"
        if "suficiente" in message:
            return "a página não trouxe o texto do artigo"
        if "timed out" in message.casefold() or "timeout" in message.casefold():
            return "tempo esgotado"
        return message[:160] or type(error).__name__

    def _retrieve_content(
        self,
        work: Any,
        key: str,
    ) -> tuple[ArticleContent | None, str | None, list[dict[str, str]]]:
        """PMC, cópias abertas localizadas e, por fim, somente o abstract.

        Devolve também cada tentativa, para explicar ao usuário por que um estudo
        ficou restrito ao abstract.
        """

        from .pmc import retrieve_article_content

        attempts: list[dict[str, str]] = []
        content: ArticleContent | None = None
        if work.pmid:
            with logged_step(logger, "article_content_retrieval", work=key) as step:
                content = retrieve_article_content(work.to_publication(), self.abstract_client)
                step["access_level"] = content.access_level
            if content.full_text:
                return content, "PubMed Central", attempts
            attempts.append(
                {
                    "source": "PubMed Central",
                    "outcome": "sem texto completo no PMC" if not content.pmcid else "PMC sem texto reutilizável",
                }
            )
        lead: FullTextLead | None = None
        if self.full_text_locator is not None and (work.doi or work.pmid or work.full_text_url):
            with logged_step(logger, "full_text_location", work=key) as step:
                lead = self.full_text_locator.locate(
                    work.doi, known_url=work.full_text_url, pmid=work.pmid
                )
                step["candidate_count"] = len(lead.candidates)
                step["consulted"] = list(lead.consulted)
            if not lead.candidates and not lead.pmcid:
                attempts.append(
                    {
                        "source": ", ".join(lead.consulted),
                        "outcome": "nenhuma cópia aberta registrada"
                        + ("" if (work.doi or lead.doi) else " (estudo sem DOI)"),
                    }
                )
        abstract = (content.abstract if content else None) or (lead.abstract if lead else None)
        pmcid = (content.pmcid if content else None) or (lead.pmcid if lead else None)
        if lead and lead.pmcid and not (content and content.pmcid):
            try:
                full_text, sections = self.abstract_client.fetch_pmc_full_text(lead.pmcid)
            except ContentRetrievalError:
                full_text, sections = None, ()
            if full_text:
                return (
                    ArticleContent(
                        pmid=key,
                        pmcid=lead.pmcid,
                        doi=work.doi,
                        abstract=abstract,
                        full_text=full_text,
                        sections=sections,
                        access_level="FULL_TEXT",
                        pubmed_url=work.url,
                        pmc_url=f"https://pmc.ncbi.nlm.nih.gov/articles/{lead.pmcid}/",
                    ),
                    "PubMed Central (via Europe PMC)",
                    attempts,
                )
            attempts.append({"source": "Europe PMC", "outcome": "PMCID sem texto reutilizável"})
        candidates = (
            lead.candidates
            if lead is not None
            else (
                (FullTextCandidate(work.full_text_url, "OpenAlex", False),)
                if work.full_text_url
                else ()
            )
        )
        if self.open_access_client is not None:
            for candidate in candidates[:5]:
                try:
                    with logged_step(
                        logger,
                        "open_access_fallback",
                        work=key,
                        source=candidate.source,
                    ):
                        retrieved = self.open_access_client.retrieve(
                            pmid=key,
                            pmcid=pmcid,
                            doi=work.doi,
                            pubmed_url=work.url,
                            full_text_url=candidate.url,
                            abstract=abstract,
                        )
                    return retrieved, candidate.source, attempts
                except OpenAccessContentError as error:
                    attempts.append(
                        {
                            "source": candidate.source,
                            "url": candidate.url,
                            "outcome": self._failure_reason(error),
                        }
                    )
                    continue
        if content is not None:
            return content, None, attempts
        if abstract:
            return (
                ArticleContent(
                    pmid=key,
                    pmcid=None,
                    doi=work.doi,
                    abstract=abstract,
                    full_text=None,
                    sections=(),
                    access_level="ABSTRACT_ONLY",
                    pubmed_url=work.url,
                    pmc_url=None,
                ),
                None,
                attempts,
            )
        return None, None, attempts

    def _analyze_documents(
        self,
        claim: str,
        works: Sequence[Any],
        max_articles: int | None = None,
        claim_profile: Mapping[str, Any] | None = None,
    ) -> tuple[
        tuple[GeminiEvidenceAssessment, ...],
        int,
        str | None,
        dict[str, dict[str, Any]],
    ]:
        if self.abstract_client is None or self.evidence_analyzer is None:
            return (), 0, None, {}
        documents: list[EvidenceDocument] = []
        content_metadata: dict[str, dict[str, Any]] = {}
        failures = 0
        limit = max_articles or self.max_analysis_articles
        for work in works:
            if len(documents) == limit:
                break
            key = work_key(work)
            if key is None:
                continue
            try:
                if not hasattr(self.abstract_client, "resolve_pmcid"):
                    # Cliente simplificado (testes): só abstracts do PubMed.
                    if not work.pmid:
                        continue
                    with logged_step(
                        logger,
                        "article_abstract_retrieval",
                        pmid=work.pmid,
                    ) as step:
                        abstract = self.abstract_client.fetch_pubmed_abstract(work.pmid)
                        step["found"] = bool(abstract)
                    if not abstract:
                        failures += 1
                        continue
                    passages = (
                        EvidencePassage(
                            passage_id=f"{work.pmid}:abstract",
                            text=abstract,
                            section="Abstract",
                            source_url=work.url,
                        ),
                    )
                    content_metadata[key] = {
                        "access_level": "ABSTRACT_ONLY",
                        "pmcid": None,
                        "pmc_url": None,
                        "analyzed_passage_count": 1,
                        "analyzed_sections": ["Abstract"],
                        "full_text_source": None,
                    }
                else:
                    content, full_text_source, attempts = self._retrieve_content(work, key)
                    if content is None:
                        failures += 1
                        continue
                    passages = select_evidence_passages(content, claim, key)
                    abstract = content.abstract or ""
                    content_metadata[key] = {
                        "access_level": content.access_level,
                        "pmcid": content.pmcid,
                        "pmc_url": content.pmc_url,
                        "analyzed_passage_count": len(passages),
                        "analyzed_sections": list(
                            dict.fromkeys(passage.section for passage in passages)
                        ),
                        "full_text_source": full_text_source,
                        "full_text_attempts": attempts,
                        "abstract": content.abstract,
                        "analyzed_passages": [
                            {
                                "section": passage.section,
                                "page": passage.page_number,
                                "text": passage.text,
                            }
                            for passage in passages
                        ],
                    }
            except (ContentRetrievalError, ChunkingError, RetrievalError):
                failures += 1
                continue
            if not passages:
                failures += 1
                continue
            documents.append(
                EvidenceDocument(
                    pmid=key,
                    title=work.title,
                    abstract=abstract,
                    source_url=work.url,
                    passages=passages,
                )
            )
        if not documents:
            return (), failures, None, content_metadata
        # Lotes pequenos mantêm a linha padronizada dentro do limite de saída, e a
        # falha de um lote (ex.: Gemini sobrecarregado) não descarta os demais.
        batches = [documents[index:index + 5] for index in range(0, len(documents), 5)]
        collected: list[GeminiEvidenceAssessment] = []
        failed_batches = 0
        for batch_index, batch in enumerate(batches, start=1):
            try:
                with logged_step(
                    logger,
                    "gemini_evidence_analysis",
                    document_count=len(batch),
                    batch=batch_index,
                ) as step:
                    batch_result = (
                        self.evidence_analyzer.analyze(claim, batch, claim_profile=claim_profile)
                        if claim_profile
                        else self.evidence_analyzer.analyze(claim, batch)
                    )
                    step["assessment_count"] = len(batch_result)
                collected.extend(batch_result)
            except GeminiAnalysisError:
                failed_batches += 1
        analysis_failure = None
        if failed_batches:
            analysis_failure = (
                f"A análise do Gemini falhou em {failed_batches} de {len(batches)} lote(s) "
                f"({sum(len(batch) for batch in batches[-failed_batches:])} estudo(s) sem avaliação)."
                if collected
                else "ANALYSIS_UNAVAILABLE: a análise estruturada do Gemini não respondeu."
            )
        return tuple(collected), failures, analysis_failure, content_metadata

    def analyze(
        self,
        claim: str,
        article_reference: str | None = None,
        *,
        excluded_dois: Sequence[str] = (),
        query_override: str | None = None,
        related_seed_pmids: Sequence[str] = (),
        seed_doi: str | None = None,
        seed_authors: Sequence[str] = (),
        search_queries: Sequence[str] = (),
        depth: str = "QUICK",
        claim_profile: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        search_depth = SEARCH_DEPTHS.get(depth, SEARCH_DEPTHS["QUICK"])
        max_results_per_query = max(
            self.max_results_per_query, search_depth.max_results_per_query
        ) if depth == "DEEP" else self.max_results_per_query
        max_articles = (
            search_depth.max_analysis_articles
            if depth == "DEEP"
            else self.max_analysis_articles
        )
        with logged_step(
            logger,
            "input_validation",
            claim_length=len(claim) if isinstance(claim, str) else 0,
            has_article_reference=bool(article_reference),
        ):
            analysis_input = validate_analysis_input(claim, article_reference)
        with logged_step(logger, "search_planning") as step:
            if search_queries:
                # Consultas booleanas por conceito vêm primeiro; a tradução livre
                # da alegação fica como rede de segurança.
                fallback = self.planner.generate_queries(
                    query_override or analysis_input.claim
                )
                clinical_filter = PUBMED_CLINICAL_FILTERS.get(
                    str((claim_profile or {}).get("claim_type") or "")
                )
                filtered = (
                    (f"({search_queries[0]}) AND {clinical_filter}",)
                    if clinical_filter
                    else ()
                )
                plan = SearchPlan(
                    claim=analysis_input.claim,
                    queries=tuple(
                        dict.fromkeys((search_queries[0], *filtered, *search_queries[1:], *fallback[:1]))
                    ),
                    article_reference=analysis_input.article_reference,
                )
            elif query_override:
                plan = SearchPlan(
                    claim=analysis_input.claim,
                    queries=tuple(self.planner.generate_queries(query_override)),
                    article_reference=analysis_input.article_reference,
                )
            else:
                plan = prepare_search_plan(analysis_input, self.planner)
            if analysis_input.article_reference:
                queries = tuple(
                    dict.fromkeys(
                        (analysis_input.article_reference, *plan.queries)
                    )
                )[:3]
                plan = SearchPlan(
                    claim=plan.claim,
                    queries=queries,
                    article_reference=plan.article_reference,
                )
            step["query_count"] = len(plan.queries)
        effective_seed_doi = seed_doi
        if not effective_seed_doi and analysis_input.reference_type == "doi":
            effective_seed_doi = analysis_input.article_reference
        with logged_step(logger, "query_expansion") as step:
            expanded_queries = expand_scientific_queries(
                analysis_input.claim,
                plan.queries,
                seed_doi=effective_seed_doi,
                seed_authors=seed_authors,
                max_queries=search_depth.max_queries,
            )
            plan = SearchPlan(
                claim=plan.claim,
                queries=tuple(item.query for item in expanded_queries),
                article_reference=plan.article_reference,
            )
            step["expanded_query_count"] = len(expanded_queries)
        try:
            with logged_step(
                logger,
                "federated_search",
                query_count=len(plan.queries),
            ) as step:
                result = self.search_engine.search(
                    plan,
                    max_results_per_query=max_results_per_query,
                )
                step["candidate_count"] = len(result.works)
                step["source_failure_count"] = len(result.failures)
        except FederatedSearchError as error:
            raise AnalysisServiceError(
                "As fontes científicas não responderam. Tente novamente em alguns instantes."
            ) from error

        with logged_step(
            logger,
            "related_article_search",
            seed_count=len(related_seed_pmids),
        ) as step:
            related_works, related_failures = self._related_works(related_seed_pmids)
            step["related_work_count"] = len(related_works)
            step["failure_count"] = len(related_failures)
        graph_works: tuple[ScientificWork, ...] = ()
        graph_query_results = ()
        graph_failures = ()
        with logged_step(
            logger,
            "citation_graph_expansion",
            enabled=bool(self.openalex_graph is not None and effective_seed_doi),
        ) as step:
            if self.openalex_graph is not None and effective_seed_doi:
                graph_result = self.openalex_graph.expand(
                    effective_seed_doi,
                    max_results=max_results_per_query,
                )
                graph_works = graph_result.works
                graph_query_results = graph_result.query_results
                graph_failures = graph_result.failures
            step["graph_work_count"] = len(graph_works)
            step["failure_count"] = len(graph_failures)
        with logged_step(logger, "deduplication") as step:
            all_works = deduplicate_works(
                (*result.works, *related_works, *graph_works),
                source_order=(
                    "PubMed",
                    "Europe PMC",
                    "PubMed relacionados",
                    "OpenAlex referências",
                    "OpenAlex citações",
                    "OpenAlex relacionados",
                    "OpenAlex",
                    "SciELO (via OpenAlex)",
                ),
            )
            step["input_count"] = (
                len(result.works) + len(related_works) + len(graph_works)
            )
            step["unique_count"] = len(all_works)
        normalized_exclusions = {
            item.strip().casefold() for item in excluded_dois if item.strip()
        }
        eligible_works = tuple(
            work
            for work in all_works
            if not work.doi or work.doi.strip().casefold() not in normalized_exclusions
        )
        with logged_step(
            logger,
            "relevance_reranking",
            eligible_count=len(eligible_works),
        ) as step:
            concept_terms = [
                term
                for group in (claim_profile or {}).get("concept_groups") or ()
                for term in group
            ]
            # Títulos são em inglês: termos de conceito ou a consulta traduzida
            # comparam melhor que o texto da alegação em português.
            reranking_basis = " ".join(concept_terms) or plan.queries[0]
            reranked = ClaimRelevanceReranker().rank(reranking_basis, eligible_works)
            works = tuple(item.work for item in reranked if item.accepted)
            reranking_by_identity = {
                (item.work.doi or item.work.pmid or item.work.url): item
                for item in reranked
            }
            step["accepted_count"] = len(works)
            step["rejected_count"] = len(reranked) - len(works)

        with logged_step(
            logger,
            "evidence_collection",
            work_count=len(works),
        ) as step:
            (
                assessments,
                content_failure_count,
                analysis_failure,
                content_metadata,
            ) = self._analyze_documents(
                analysis_input.claim,
                works,
                max_articles=max_articles,
                claim_profile=claim_profile,
            )
            step["assessment_count"] = len(assessments)
            step["content_failure_count"] = content_failure_count
        assembly_started = perf_counter()
        log_event(
            logger,
            logging.INFO,
            "Etapa iniciada: result_assembly",
            event="pipeline.step",
            stage="result_assembly",
            status="started",
        )
        if self.pubmed_only:
            designs = {
                work_key(work): classify_study_design("", None, publication_types=work.publication_types).design.value
                for work in works
            }
            assessments = tuple(replace(item, study_design=designs.get(item.pmid, "UNKNOWN")) for item in assessments)
        assessments_by_pmid = {item.pmid: item for item in assessments}
        editorial_by_identity: dict[str, tuple[str, str | None]] = {}
        with logged_step(logger, "editorial_status_check") as step:
            for work in works:
                if self.pubmed_only or work_key(work) in assessments_by_pmid:
                    editorial_by_identity[work.doi or work.pmid or work.url] = (
                        self._editorial_status(work)
                    )
            step["checked_count"] = len(editorial_by_identity)
            step["flagged_count"] = sum(
                status not in {"PUBLISHED", "UNKNOWN"}
                for status, _detail in editorial_by_identity.values()
            )

        articles = [
            {
                "pmid": work.pmid,
                "title": work.title,
                "authors": list(work.authors),
                "journal": work.journal,
                "publication_date": work.publication_date,
                "doi": work.doi,
                "url": work.url,
                "publication_types": list(work.publication_types),
                "editorial_status": editorial_by_identity.get(
                    work.doi or work.pmid or work.url, ("UNKNOWN", None)
                )[0],
                "editorial_detail": editorial_by_identity.get(
                    work.doi or work.pmid or work.url, ("UNKNOWN", None)
                )[1],
                "access_level": content_metadata.get(work_key(work) or "", {}).get(
                    "access_level",
                    "METADATA_ONLY",
                ),
                "pmcid": content_metadata.get(work_key(work) or "", {}).get("pmcid"),
                "pmc_url": content_metadata.get(work_key(work) or "", {}).get("pmc_url"),
                "analyzed_passage_count": content_metadata.get(work_key(work) or "", {}).get(
                    "analyzed_passage_count", 0
                ),
                "analyzed_sections": content_metadata.get(work_key(work) or "", {}).get(
                    "analyzed_sections", []
                ),
                "full_text_source": content_metadata.get(work_key(work) or "", {}).get(
                    "full_text_source"
                ),
                "full_text_attempts": content_metadata.get(work_key(work) or "", {}).get(
                    "full_text_attempts", []
                ),
                "abstract": content_metadata.get(work_key(work) or "", {}).get("abstract"),
                "analyzed_passages": content_metadata.get(work_key(work) or "", {}).get(
                    "analyzed_passages", []
                ),
                "work_key": work_key(work),
                "quality": {
                    "study_design": (
                        classify_study_design("", None, publication_types=work.publication_types).design.value
                        if self.pubmed_only
                        else assessments_by_pmid[work_key(work)].study_design
                        if work_key(work) in assessments_by_pmid
                        else "NOT_ASSESSED"
                    ),
                    "level": "NOT_EVALUATED",
                    "is_retracted": editorial_by_identity.get(
                        work.doi or work.pmid or work.url, ("UNKNOWN", None)
                    )[0] == "RETRACTED",
                    "rationale": "A qualidade ainda não foi avaliada nesta prévia.",
                    "checks": [],
                    "datasets": [],
                    "trial_registrations": [],
                },
                "assessments": (
                    [
                        {
                            "relation": assessments_by_pmid[work_key(work)].relation,
                            "confidence": assessments_by_pmid[work_key(work)].confidence,
                            "rationale": assessments_by_pmid[work_key(work)].rationale,
                            "model_name": assessments_by_pmid[work_key(work)].model_name,
                            "evidence": {
                                "text": assessments_by_pmid[work_key(work)].evidence_quote,
                                "section": assessments_by_pmid[work_key(work)].evidence_section,
                                "page": assessments_by_pmid[work_key(work)].evidence_page,
                                "content_scope": assessments_by_pmid[work_key(work)].content_scope,
                                "passage_id": assessments_by_pmid[work_key(work)].passage_id,
                                "pmid": work.pmid,
                                "doi": work.doi,
                                "source_url": (
                                    assessments_by_pmid[work_key(work)].source_url or work.url
                                ),
                            },
                            "study_row": (
                                dict(assessments_by_pmid[work_key(work)].study_row)
                                if getattr(assessments_by_pmid[work_key(work)], "study_row", None)
                                else None
                            ),
                        }
                    ]
                    if work_key(work) in assessments_by_pmid
                    else []
                ),
                "retrieval": {
                    "sources": list(work.sources),
                    "score": work.retrieval_score,
                    "matched_queries": list(work.matched_queries),
                    "citation_count": work.citation_count,
                    "related_work_count": work.related_work_count,
                    "reranking_score": reranking_by_identity[
                        work.doi or work.pmid or work.url
                    ].score,
                    "concept_matches": list(
                        reranking_by_identity[work.doi or work.pmid or work.url].concept_matches
                    ),
                    "reranking_reasons": list(
                        reranking_by_identity[work.doi or work.pmid or work.url].reasons
                    ),
                },
            }
            for work in works
        ]
        limitations = [
            (
                "A análise priorizou texto completo quando disponível e usou abstracts "
                "somente como fallback explicitamente identificado."
                if assessments
                else "Esta execução recuperou artigos, mas não analisou seus resultados."
            ),
            "A classificação indica compatibilidade textual, nunca verdade médica.",
            "A tradução automática da consulta pode alterar termos ou nuances clínicas.",
            "A ordem é um ranking de recuperação, não um ranking de qualidade científica.",
        ]
        if result.failures:
            failed_sources = ", ".join(
                dict.fromkeys(failure.source for failure in result.failures)
            )
            limitations.append(
                f"Algumas consultas falharam nas fontes: {failed_sources}."
            )
        if content_failure_count:
            limitations.append(
                f"{content_failure_count} texto(s) científico(s) não puderam ser recuperados."
            )
        if analysis_failure:
            limitations.append(analysis_failure.removeprefix("ANALYSIS_UNAVAILABLE: ").capitalize())
        if related_failures:
            limitations.append(
                "A expansão por artigos relacionados do PubMed falhou parcialmente."
            )
        if graph_failures:
            limitations.append(
                "A expansão de referências, citações ou relacionados do OpenAlex falhou parcialmente."
            )
        rejected_count = sum(not item.accepted for item in reranked)
        if rejected_count:
            limitations.append(
                f"O reranker excluiu {rejected_count} candidato(s) com cobertura temática insuficiente no título."
            )

        usable = tuple(item for item in assessments if item.relation != "UNCERTAIN")
        relation_counts = {
            relation: sum(item.relation == relation for item in usable)
            for relation in ("SUPPORTS", "CONTRADICTS", "NEUTRAL")
        }
        if relation_counts["SUPPORTS"] and relation_counts["CONTRADICTS"]:
            direction = "MIXED"
        elif relation_counts["SUPPORTS"] > relation_counts["CONTRADICTS"]:
            direction = "SUPPORTS"
        elif relation_counts["CONTRADICTS"] > relation_counts["SUPPORTS"]:
            direction = "CONTRADICTS"
        else:
            direction = "NEUTRAL"
        strength = "LOW" if usable else "INSUFFICIENT"
        probability_denominator = len(usable) or 1
        conclusion_by_direction = {
            "SUPPORTS": "COMPATIBLE_WITH_EVIDENCE",
            "CONTRADICTS": "INCOMPATIBLE_WITH_EVIDENCE",
            "MIXED": "CONFLICTING_EVIDENCE",
            "NEUTRAL": "INCONCLUSIVE",
        }
        headline_by_conclusion = {
            "COMPATIBLE_WITH_EVIDENCE": "Compatibilidade preliminar nos trechos analisados",
            "INCOMPATIBLE_WITH_EVIDENCE": "Incompatibilidade preliminar nos trechos analisados",
            "CONFLICTING_EVIDENCE": "Resultados conflitantes nos trechos analisados",
            "INCONCLUSIVE": "Trechos sem direção clara",
            "INSUFFICIENT_EVIDENCE": "Evidência ainda não analisada",
        }
        conclusion = (
            conclusion_by_direction[direction]
            if usable
            else "INSUFFICIENT_EVIDENCE"
        )
        if not works:
            summary = (
                "Nenhum trabalho foi localizado nas fontes que responderam. Isso não "
                "demonstra que a alegação seja falsa."
            )
        elif assessments:
            summary = (
                f"{len(assessments)} artigo(s) tiveram trechos analisados: "
                f"{relation_counts['SUPPORTS']} compatível(is), "
                f"{relation_counts['CONTRADICTS']} incompatível(is), "
                f"{relation_counts['NEUTRAL']} neutro(s) e "
                f"{len(assessments) - len(usable)} incerto(s)."
            )
        else:
            summary = (
                f"Foram localizados {len(works)} trabalhos únicos. Abra as "
                "fontes para conferir a relação com a alegação; a interpretação "
                "científica ainda não foi executada."
            )
        sources = [
            {
                "label": f"{', '.join(work.sources)}: {work.title}",
                "url": work.url,
                "pmid": work.pmid,
            }
            for work in works
        ]
        response = {
            "input": {
                "claim": analysis_input.claim,
                "article_reference": analysis_input.article_reference,
                "reference_type": analysis_input.reference_type,
            },
            "search": {
                "queries": list(plan.queries),
                "query_expansion": [
                    {
                        "query": item.query,
                        "strategy": item.strategy,
                        "explanation": item.explanation,
                    }
                    for item in expanded_queries
                ],
                "query_results": [
                    {
                        "source": item.source,
                        "query": item.query,
                        "total_matches": item.total_matches,
                        "retrieved_count": item.retrieved_count,
                    }
                    for item in result.query_results
                ]
                + [
                    {
                        "source": item.source,
                        "query": item.query,
                        "total_matches": item.total_matches,
                        "retrieved_count": item.retrieved_count,
                    }
                    for item in graph_query_results
                ]
                + (
                    [
                        {
                            "source": "PubMed relacionados",
                            "query": ", ".join(related_seed_pmids),
                            "total_matches": len(related_works),
                            "retrieved_count": len(related_works),
                        }
                    ]
                    if related_seed_pmids
                    else []
                ),
                "candidate_count": len(all_works),
                "unique_work_count": len(works),
                "reranking": {
                    "basis": reranking_basis,
                    "evaluated_count": len(reranked),
                    "accepted_count": len(works),
                    "rejected_count": rejected_count,
                    "rejected": [
                        {
                            "title": item.work.title,
                            "doi": item.work.doi,
                            "pmid": item.work.pmid,
                            "score": item.score,
                            "concept_matches": list(item.concept_matches),
                            "reasons": list(item.reasons),
                        }
                        for item in reranked
                        if not item.accepted
                    ][:20],
                },
                "unresolved_work_count": len(result.unresolved_works),
                "source_failure_count": (
                    len(result.failures) + len(related_failures) + len(graph_failures)
                ),
            },
            "articles": articles,
            "failures": [
                {
                    "source": item.source,
                    "query": item.query,
                    "reason": item.reason,
                }
                for item in result.failures
            ]
            + [
                {
                    "source": "PubMed relacionados",
                    "query": ", ".join(related_seed_pmids),
                    "reason": reason,
                }
                for reason in related_failures
            ]
            + [
                {
                    "source": item.source,
                    "query": item.query,
                    "reason": item.reason,
                }
                for item in graph_failures
            ],
            "synthesis": {
                "direction": direction,
                "strength": strength,
                "article_count": len(works),
                "usable_article_count": len(usable),
                "has_conflict": direction == "MIXED",
                "probabilities": {
                    "support": relation_counts["SUPPORTS"] / probability_denominator,
                    "contradiction": (
                        relation_counts["CONTRADICTS"] / probability_denominator
                    ),
                    "neutral": relation_counts["NEUTRAL"] / probability_denominator,
                },
                "rationale": (
                    "Classificação baseada nos trechos recuperados, priorizando texto completo."
                    if assessments
                    else "Interpretação indisponível na execução."
                ),
                "articles": [],
            },
            "report": {
                "conclusion": conclusion,
                "headline": headline_by_conclusion[conclusion],
                "summary": summary,
                "methodology": [],
                "limitations": limitations,
                "sources": sources,
            },
            "verification": (
                build_abstract_analysis_cards(
                    claim=analysis_input.claim,
                    article_reference=analysis_input.article_reference,
                    retrieved_article_count=len(works),
                    assessments=assessments,
                    content_failure_count=content_failure_count,
                )
                if assessments
                else build_unassessed_cards(
                    claim=analysis_input.claim,
                    article_reference=analysis_input.article_reference,
                    retrieved_article_count=len(works),
                )
            ),
        }
        response["weighted_evidence"] = synthesize_evidence(
            articles,
            candidate_count=len(all_works),
            claim_profile=claim_profile,
            analysis_unavailable=bool(
                analysis_failure and analysis_failure.startswith("ANALYSIS_UNAVAILABLE")
            ),
            sources=list(
                dict.fromkeys(
                    source for work in all_works for source in work.sources
                )
            ),
            queries=plan.queries,
            assess_methodology=False,
        )
        if self.trial_registry is not None and claim_profile:
            with logged_step(logger, "trial_registry_lookup") as step:
                response["trial_registry"] = self.trial_registry.summarize(claim_profile)
                step["registered_count"] = (response["trial_registry"] or {}).get(
                    "registered_count"
                )
        response["reproducibility"] = {
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "evidence_model": getattr(self.evidence_analyzer, "model_name", None),
            "translation_model": getattr(
                getattr(self.planner, "translator", None), "model_name", None
            ),
            "depth": search_depth.code,
            "parameters": {
                "max_queries": search_depth.max_queries,
                "max_results_per_query": max_results_per_query,
                "max_analysis_articles": max_articles,
                "chunk_words": 220,
                "chunk_overlap_words": 40,
                "passages_per_article": 4,
                "temperature": 0,
            },
            "queries": list(plan.queries),
            "claim_profile": dict(claim_profile) if claim_profile else None,
        }
        response["user_summary"] = build_user_summary(response)
        log_event(
            logger,
            logging.INFO,
            "Etapa concluída: result_assembly",
            event="pipeline.step",
            stage="result_assembly",
            status="completed",
            duration_ms=round((perf_counter() - assembly_started) * 1000, 2),
            article_count=len(articles),
            assessment_count=len(assessments),
            conclusion=response["report"]["conclusion"],
        )
        return response


_PORTUGUESE_STOPWORDS = frozenset(
    """a o as os um uma uns umas de da do das dos em no na nos nas por para com sem
    que se e ou é são foi foram ser pode podem mais menos entre sobre como ao aos à às
    seu sua seus suas este esta estes estas esse essa isso pelo pela pelos pelas""".split()
)


def portuguese_keywords(text: str) -> str:
    terms = [
        token
        for token in re.findall(r"[^\W\d_]+", text.casefold(), flags=re.UNICODE)
        if len(token) >= 4 and token not in _PORTUGUESE_STOPWORDS
    ]
    return " ".join(list(dict.fromkeys(terms))[:8])


def _refresh_claim_result(result: dict[str, Any]) -> dict[str, Any]:
    """Recalcula síntese e resumo depois de alterar artigos de um resultado."""

    previous = result.get("weighted_evidence") or {}
    result["weighted_evidence"] = synthesize_evidence(
        result.get("articles") or (),
        candidate_count=(result.get("search") or {}).get("candidate_count", 0),
        claim_profile=(result.get("reproducibility") or {}).get("claim_profile"),
        submitted_population=(result.get("reproducibility") or {}).get("submitted_population") or (),
        sources=list(
            dict.fromkeys(
                source
                for article in result.get("articles") or ()
                for source in (article.get("retrieval") or {}).get("sources") or ()
            )
        ),
        queries=previous.get("queries") or (),
        assess_methodology=False,
    )
    result["user_summary"] = build_user_summary(result)
    return result


class StudyTools:
    """Ações sobre uma análise concluída, sem refazer a busca inteira."""

    def __init__(
        self,
        runner: RetrievalPreviewRunner,
        document_parser: LiteParseDocumentParser | None,
    ) -> None:
        self.runner = runner
        self.document_parser = document_parser

    def reassess_with_full_text(
        self,
        claim_result: Mapping[str, Any],
        *,
        claim_text: str,
        claim_profile: Mapping[str, Any] | None,
        study_key: str,
        pdf_bytes: bytes,
    ) -> dict[str, Any]:
        if self.document_parser is None or self.runner.evidence_analyzer is None:
            raise AnalysisServiceError("A leitura de PDFs não está configurada.")
        result = json.loads(json.dumps(claim_result))
        articles = result.get("articles") or []
        article = next(
            (
                item
                for item in articles
                if (item.get("work_key") or item.get("pmid") or (f"doi:{item['doi']}" if item.get("doi") else None))
                == study_key
            ),
            None,
        )
        if article is None:
            raise InputValidationError("O estudo indicado não pertence a esta alegação.")
        try:
            with logged_step(logger, "user_pdf_parsing", work=study_key) as step:
                parsed = self.document_parser.parse_pdf(pdf_bytes)
                step["page_count"] = parsed.page_count
        except DocumentParsingError as error:
            raise InputValidationError(f"Não foi possível ler o PDF: {error}") from error
        source_url = article.get("url") or "https://doi.org/" + str(article.get("doi") or "")
        content = ArticleContent(
            pmid=study_key,
            pmcid=article.get("pmcid"),
            doi=article.get("doi"),
            abstract=None,
            full_text=parsed.text,
            sections=tuple(
                ContentSection(title="Página do PDF", text=page.text, page_number=page.page_number)
                for page in getattr(parsed, "pages", ()) or ()
            )
            or (ContentSection("Texto completo", parsed.text),),
            access_level="USER_PROVIDED_FULL_TEXT",
            pubmed_url=source_url,
            # O chunking cita o texto completo pela URL do documento.
            pmc_url=source_url,
        )
        try:
            passages = select_evidence_passages(content, claim_text, study_key)
        except ChunkingError as error:
            raise InputValidationError(f"O PDF não pôde ser dividido em trechos: {error}") from error
        if not passages:
            raise InputValidationError("O PDF não trouxe texto suficiente para análise.")
        document = EvidenceDocument(
            pmid=study_key,
            title=article.get("title") or "Estudo enviado",
            abstract="",
            source_url=source_url,
            passages=passages,
        )
        with logged_step(logger, "user_pdf_assessment", work=study_key):
            assessments = self.runner.evidence_analyzer.analyze(
                claim_text, [document], claim_profile=claim_profile
            ) if claim_profile else self.runner.evidence_analyzer.analyze(claim_text, [document])
        if not assessments:
            raise AnalysisServiceError("O modelo não devolveu avaliação para o PDF enviado.")
        assessment = assessments[0]
        article["access_level"] = "USER_PROVIDED_FULL_TEXT"
        article["full_text_source"] = "PDF enviado pelo usuário"
        article["analyzed_passage_count"] = len(passages)
        article["analyzed_sections"] = list(dict.fromkeys(item.section for item in passages))
        if not self.runner.pubmed_only:
            article.setdefault("quality", {})["study_design"] = assessment.study_design
        article["assessments"] = [
            {
                "relation": assessment.relation,
                "confidence": assessment.confidence,
                "rationale": assessment.rationale,
                "model_name": assessment.model_name,
                "evidence": {
                    "text": assessment.evidence_quote,
                    "section": assessment.evidence_section,
                    "page": assessment.evidence_page,
                    "content_scope": assessment.content_scope,
                    "passage_id": assessment.passage_id,
                    "pmid": article.get("pmid"),
                    "doi": article.get("doi"),
                    "source_url": source_url,
                },
                "study_row": dict(assessment.study_row) if assessment.study_row else None,
            }
        ]
        return _refresh_claim_result(result)

    def complementary_search(
        self,
        claim_result: Mapping[str, Any],
        *,
        claim_text: str,
        claim_profile: Mapping[str, Any] | None,
        excluded_dois: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Amplia a busca sem repetir o que já foi lido.

        Estratégias: bola de neve (referências e citações do estudo de maior peso),
        consulta ampliada com menos conceitos, termos em português para SciELO e
        Europe PMC (que também busca no texto completo aberto).
        """

        result = json.loads(json.dumps(claim_result))
        articles = result.get("articles") or []
        known = {
            identity
            for article in articles
            for identity in (article.get("doi"), article.get("pmid"), article.get("work_key"))
            if identity
        }
        rows = (result.get("weighted_evidence") or {}).get("rows") or []
        seeds = [row for row in sorted(rows, key=lambda item: -(item.get("weight") or 0)) if row.get("doi")]
        groups = [list(group) for group in (claim_profile or {}).get("concept_groups") or ()]
        queries: list[str] = []
        if len(groups) >= 2:
            # Retirar conceito só com 3 ou mais: com 2, a consulta fica genérica demais.
            queries += list(boolean_queries(groups))
        if groups:
            # Sinônimos de cada conceito ampliam a revocação no Europe PMC.
            queries.append(" AND ".join(
                "(" + " OR ".join(f'"{term}"' for term in group) + ")" for group in groups
            ))
        portuguese = portuguese_keywords(claim_text)
        if portuguese:
            queries.append(portuguese)
        queries = list(dict.fromkeys(query for query in queries if query))[:5]
        if not queries:
            raise AnalysisServiceError("A alegação não tem conceitos suficientes para ampliar a busca.")
        extra = self.runner.analyze(
            claim_text,
            None,
            excluded_dois=tuple(dict.fromkeys((*excluded_dois, *(item for item in known if "/" in item)))),
            search_queries=tuple(queries),
            depth="DEEP",
            claim_profile=claim_profile,
            seed_doi=seeds[0]["doi"] if seeds else None,
        )
        added = []
        discarded = 0
        for article in extra.get("articles") or []:
            identities = {article.get("doi"), article.get("pmid"), article.get("work_key")} - {None}
            if identities & known:
                continue
            assessment = (article.get("assessments") or [None])[0]
            if assessment is None:
                # Não lido não acrescenta evidência; só incharia a tabela.
                discarded += 1
                continue
            if assessment is not None:
                row = assessment.get("study_row") or {}
                if (
                    row.get("comparability", "INDIRECT") == "INDIRECT"
                    and assessment.get("relation") not in {"SUPPORTS", "CONTRADICTS"}
                ):
                    # Ampliar a busca traz ruído: indireto e neutro não entra na síntese.
                    discarded += 1
                    continue
            article.setdefault("retrieval", {}).setdefault("sources", [])
            article["retrieval"]["complementary"] = True
            added.append(article)
            known |= identities
        result["articles"] = articles + added
        search = result.setdefault("search", {})
        search["candidate_count"] = (search.get("candidate_count") or 0) + (
            (extra.get("search") or {}).get("candidate_count") or 0
        )
        result["complementary"] = {
            "status": "DONE",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "queries": queries,
            "seed_doi": seeds[0]["doi"] if seeds else None,
            "candidate_count": (extra.get("search") or {}).get("candidate_count") or 0,
            "added_count": len(added),
            "discarded_indirect_count": discarded,
            "added_assessed_count": sum(bool(item.get("assessments")) for item in added),
        }
        reproducibility = result.setdefault("reproducibility", {})
        reproducibility["complementary_queries"] = queries
        if extra.get("trial_registry") and not result.get("trial_registry"):
            result["trial_registry"] = extra["trial_registry"]
        return _refresh_claim_result(result)

    def find_new_studies(self, claim_result: Mapping[str, Any]) -> dict[str, Any]:
        """Repete as consultas registradas e lista trabalhos ainda não vistos."""

        reproducibility = claim_result.get("reproducibility") or {}
        queries = tuple(reproducibility.get("queries") or ())
        if not queries:
            raise AnalysisServiceError("Esta análise não registrou as consultas usadas.")
        claim_text = (claim_result.get("input") or {}).get("claim") or "alegação"
        with logged_step(logger, "new_studies_check", query_count=len(queries)) as step:
            found = self.runner.search_engine.search(
                SearchPlan(claim=claim_text, queries=queries),
                max_results_per_query=self.runner.max_results_per_query,
            )
            step["candidate_count"] = len(found.works)
        known = {
            identity
            for article in claim_result.get("articles") or ()
            for identity in (article.get("doi"), article.get("pmid"), article.get("url"))
            if identity
        }
        known |= {
            identity
            for item in ((claim_result.get("search") or {}).get("reranking") or {}).get("rejected") or ()
            for identity in (item.get("doi"), item.get("pmid"))
            if identity
        }
        executed_year = str(reproducibility.get("executed_at") or "")[:4]
        new_studies = []
        for work in found.works:
            if {work.doi, work.pmid, work.url} & known:
                continue
            year = re.search(r"(19|20)\d{2}", str(work.publication_date or ""))
            new_studies.append(
                {
                    "title": work.title,
                    "year": int(year.group(0)) if year else None,
                    "journal": work.journal,
                    "doi": work.doi,
                    "pmid": work.pmid,
                    "url": work.url,
                    "sources": list(work.sources),
                    "published_after_analysis": bool(
                        year and executed_year.isdigit() and int(year.group(0)) >= int(executed_year)
                    ),
                }
            )
        new_studies.sort(key=lambda item: item["year"] or 0, reverse=True)
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "queries": list(queries),
            "new_study_count": len(new_studies),
            "new_studies": new_studies[:30],
        }


def _optional_browser_fetcher() -> Crawl4AiFetcher | None:
    """Ativa o navegador headless só quando instalado e habilitado."""

    if os.getenv("ENABLE_CRAWL4AI", "").lower() not in {"1", "true", "yes"}:
        return None
    try:
        return Crawl4AiFetcher(timeout=float(os.getenv("CRAWL4AI_TIMEOUT", "45")))
    except ImportError:
        logger.warning("ENABLE_CRAWL4AI ativo, mas o pacote crawl4ai não está instalado.")
        return None


def create_pubmed_only_app(*, project_root: Path | None = None):
    """Compõe o MVP sem instanciar conectores de literatura externos ao NCBI."""
    root = project_root or Path(__file__).resolve().parents[2]
    _load_env(root / ".env")
    timeout = float(os.getenv("HTTP_TIMEOUT", "20"))
    email = os.getenv("NCBI_EMAIL") or None
    pubmed_client = PubMedClient(
        email=email,
        api_key=os.getenv("NCBI_API_KEY") or None,
        timeout=timeout,
    )
    pmc_client = PmcClient(
        email=email,
        api_key=os.getenv("NCBI_API_KEY") or None,
        timeout=timeout,
    )
    engine = FederatedSearchEngine(
        (
            PubMedSearchProvider(pubmed_client),
        )
    )
    translator = MarianPortugueseEnglishTranslator(
        os.getenv("TRANSLATION_MODEL", "Helsinki-NLP/opus-mt-ROMANCE-en")
    )
    evidence_analyzer = (
        GeminiEvidenceAnalyzer(
            os.environ["GEMINI_API_KEY"],
            model_name=os.getenv("LLM_MODEL", "gemini-flash-lite-latest"),
            timeout=float(os.getenv("LLM_TIMEOUT", "120")),
            max_attempts=int(os.getenv("LLM_MAX_ATTEMPTS", "3")),
            retry_backoff=float(os.getenv("LLM_RETRY_BACKOFF", "1")),
            assess_methodology=False,
        )
        if os.getenv("GEMINI_API_KEY")
        else None
    )
    try:
        document_parser = LiteParseDocumentParser(
            max_pages=int(os.getenv("DOCUMENT_MAX_PAGES", "100")),
            parse_timeout=float(os.getenv("DOCUMENT_PARSE_TIMEOUT", "45")),
        )
    except DocumentParsingError:
        document_parser = None
    runner = RetrievalPreviewRunner(
        engine,
        planner=GenericHealthQueryPlanner(translator),
        abstract_client=pmc_client,
        evidence_analyzer=evidence_analyzer,
        related_client=pubmed_client,
        pubmed_only=True,
    )
    service = AnalysisJobService(
        runner,
        store=SQLiteAnalysisJobStore(
            os.getenv("JOB_DATABASE_PATH", str(root / "data" / "analysis-jobs-pubmed.sqlite3"))
        ),
        result_serializer=lambda result: result,
        article_runner=(
            ArticleFirstAnalysisRunner(
                GeminiArticleExtractor(evidence_analyzer),
                runner,
                PubMedReferenceResolver(pubmed_client, pmc_client),
                document_parser,
                GeminiWholeArticleAnalyzer(evidence_analyzer),
                claim_structurer=GeminiClaimStructurer(evidence_analyzer),
                pubmed_only=True,
            )
            if evidence_analyzer is not None
            else None
        ),
        study_tools=StudyTools(runner, document_parser),
        max_workers=2,
    )
    search_gateway = (
        GeminiEvidenceAnalyzer(
            os.environ["GEMINI_API_KEY"],
            model_name=os.getenv("LLM_MODEL", "gemini-flash-lite-latest"),
            timeout=20,
            max_attempts=1,
            assess_methodology=False,
        )
        if evidence_analyzer is not None
        else None
    )
    app = create_app(
        service,
        mode_label=RETRIEVAL_MODE_LABEL,
        article_search=PubMedTopicSearch(pubmed_client, search_gateway),
    )
    app.extensions["fatofake_job_service"] = service
    _start_watch_thread(service)
    return app


def create_live_retrieval_app(*, project_root: Path | None = None):
    """Mantém o entrypoint existente usando o factory PubMed/PMC."""
    return create_pubmed_only_app(project_root=project_root)


def _start_watch_thread(service: AnalysisJobService) -> None:
    """Procura novos estudos periodicamente para análises acompanhadas."""

    try:
        interval_hours = float(os.getenv("WATCH_INTERVAL_HOURS", "24"))
    except ValueError:
        interval_hours = 24.0
    if interval_hours <= 0:
        return

    def loop() -> None:
        while True:
            time.sleep(interval_hours * 3600)
            with logged_step(logger, "watch_cycle") as step:
                step["checked_count"] = service.run_watch_cycle()

    Thread(target=loop, name="fatofake-watch", daemon=True).start()
