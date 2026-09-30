"""Aplicação de prévia que aceita alegações gerais e usa busca científica real."""

from __future__ import annotations

import os
import re
from threading import Lock
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .analysis_service import AnalysisServiceError
from .api import AnalysisJobService, create_app
from .article_ingestion import (
    ArticleFirstAnalysisRunner,
    GeminiArticleExtractor,
    PubMedReferenceResolver,
)
from .document_parsing import DocumentParsingError, LiteParseDocumentParser
from .gemini_evidence import (
    EvidenceDocument,
    GeminiAnalysisError,
    GeminiEvidenceAnalyzer,
    GeminiEvidenceAssessment,
)
from .federated_search import (
    FederatedSearchEngine,
    FederatedSearchError,
    OpenAlexClient,
    OpenAlexSearchProvider,
    PubMedSearchProvider,
    ScieloSearchProvider,
    ScientificWork,
    SourceRank,
    deduplicate_works,
    normalize_doi,
    normalize_pmid,
)
from .input_validation import validate_analysis_input
from .pmc import ContentRetrievalError, PmcClient
from .pubmed import PubMedClient, PubMedError
from .search_preparation import SearchPlan, prepare_search_plan
from .verification_cards import (
    build_abstract_analysis_cards,
    build_unassessed_cards,
)


RETRIEVAL_MODE_LABEL = (
    "BUSCA REAL — abstracts analisados pelo Gemini com limitações explícitas"
)
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
            translated = self.translator.translate(compact) if self.translator else ""
        except Exception:
            # A indisponibilidade do modelo não deve impedir a busca. O texto
            # original ainda pode encontrar trabalhos indexados em português.
            translated = ""
        candidates = (
            translated,
            self._keywords(translated),
            compact,
            self._keywords(compact),
        )
        return list(
            dict.fromkeys(
                candidate for candidate in candidates if candidate.strip()
            )
        )[:3]


class RetrievalPreviewRunner:
    """Recupera metadados reais, mas se abstém de interpretar os artigos."""

    def __init__(
        self,
        search_engine: FederatedSearchEngine,
        *,
        planner: GenericHealthQueryPlanner | None = None,
        abstract_client: PmcClient | None = None,
        evidence_analyzer: GeminiEvidenceAnalyzer | None = None,
        related_client: PubMedClient | None = None,
        max_results_per_query: int = 5,
        max_analysis_articles: int = 5,
    ) -> None:
        if max_analysis_articles < 1:
            raise ValueError("max_analysis_articles deve ser maior que zero.")
        self.search_engine = search_engine
        self.planner = planner or GenericHealthQueryPlanner()
        self.abstract_client = abstract_client
        self.evidence_analyzer = evidence_analyzer
        self.related_client = related_client
        self.max_results_per_query = max_results_per_query
        self.max_analysis_articles = max_analysis_articles

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
                    )
                )
        return tuple(works), tuple(failures)

    def _analyze_abstracts(
        self,
        claim: str,
        works: Sequence[Any],
    ) -> tuple[tuple[GeminiEvidenceAssessment, ...], int, str | None]:
        if self.abstract_client is None or self.evidence_analyzer is None:
            return (), 0, None
        documents: list[EvidenceDocument] = []
        failures = 0
        for work in works:
            if len(documents) == self.max_analysis_articles:
                break
            if not work.pmid:
                continue
            try:
                abstract = self.abstract_client.fetch_pubmed_abstract(work.pmid)
            except ContentRetrievalError:
                failures += 1
                continue
            if not abstract:
                failures += 1
                continue
            documents.append(
                EvidenceDocument(
                    pmid=work.pmid,
                    title=work.title,
                    abstract=abstract,
                    source_url=work.url,
                )
            )
        if not documents:
            return (), failures, None
        try:
            assessments = self.evidence_analyzer.analyze(claim, documents)
        except GeminiAnalysisError:
            return (), failures, "A análise estruturada do Gemini não respondeu."
        return assessments, failures, None

    def analyze(
        self,
        claim: str,
        article_reference: str | None = None,
        *,
        excluded_dois: Sequence[str] = (),
        query_override: str | None = None,
        related_seed_pmids: Sequence[str] = (),
    ) -> Mapping[str, Any]:
        analysis_input = validate_analysis_input(claim, article_reference)
        if query_override:
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
        try:
            result = self.search_engine.search(
                plan,
                max_results_per_query=self.max_results_per_query,
            )
        except FederatedSearchError as error:
            raise AnalysisServiceError(
                "As fontes científicas não responderam. Tente novamente em alguns instantes."
            ) from error

        related_works, related_failures = self._related_works(related_seed_pmids)
        all_works = deduplicate_works(
            (*result.works, *related_works),
            source_order=(
                "PubMed",
                "PubMed relacionados",
                "OpenAlex",
                "SciELO (via OpenAlex)",
            ),
        )
        normalized_exclusions = {
            item.strip().casefold() for item in excluded_dois if item.strip()
        }
        works = tuple(
            work
            for work in all_works
            if not work.doi or work.doi.strip().casefold() not in normalized_exclusions
        )

        assessments, content_failure_count, analysis_failure = self._analyze_abstracts(
            analysis_input.claim,
            works,
        )
        assessments_by_pmid = {item.pmid: item for item in assessments}

        articles = [
            {
                "pmid": work.pmid,
                "title": work.title,
                "authors": list(work.authors),
                "journal": work.journal,
                "publication_date": work.publication_date,
                "doi": work.doi,
                "url": work.url,
                "access_level": (
                    "ABSTRACT_ONLY" if work.pmid in assessments_by_pmid else "METADATA_ONLY"
                ),
                "pmcid": None,
                "pmc_url": None,
                "quality": {
                    "study_design": (
                        assessments_by_pmid[work.pmid].study_design
                        if work.pmid in assessments_by_pmid
                        else "NOT_ASSESSED"
                    ),
                    "level": "UNCLEAR",
                    "is_retracted": False,
                    "rationale": "A qualidade ainda não foi avaliada nesta prévia.",
                    "checks": [],
                    "datasets": [],
                    "trial_registrations": [],
                },
                "assessments": (
                    [
                        {
                            "relation": assessments_by_pmid[work.pmid].relation,
                            "confidence": assessments_by_pmid[work.pmid].confidence,
                            "rationale": assessments_by_pmid[work.pmid].rationale,
                            "model_name": assessments_by_pmid[work.pmid].model_name,
                            "evidence": {
                                "text": assessments_by_pmid[work.pmid].evidence_quote,
                                "section": "Abstract",
                                "pmid": work.pmid,
                                "doi": work.doi,
                                "source_url": work.url,
                            },
                        }
                    ]
                    if work.pmid in assessments_by_pmid
                    else []
                ),
                "retrieval": {
                    "sources": list(work.sources),
                    "score": work.retrieval_score,
                    "matched_queries": list(work.matched_queries),
                    "citation_count": work.citation_count,
                    "related_work_count": work.related_work_count,
                },
            }
            for work in works
        ]
        limitations = [
            (
                "A análise automática usa apenas abstracts; métodos, tabelas e o texto "
                "completo ainda não foram conferidos."
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
                f"{content_failure_count} abstract(s) não puderam ser recuperados."
            )
        if analysis_failure:
            limitations.append(analysis_failure)
        if related_failures:
            limitations.append(
                "A expansão por artigos relacionados do PubMed falhou parcialmente."
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
            "COMPATIBLE_WITH_EVIDENCE": "Compatibilidade preliminar nos abstracts",
            "INCOMPATIBLE_WITH_EVIDENCE": "Incompatibilidade preliminar nos abstracts",
            "CONFLICTING_EVIDENCE": "Resultados conflitantes nos abstracts",
            "INCONCLUSIVE": "Abstracts sem direção clara",
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
                f"{len(assessments)} abstract(s) foram analisados: "
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
        return {
            "input": {
                "claim": analysis_input.claim,
                "article_reference": analysis_input.article_reference,
                "reference_type": analysis_input.reference_type,
            },
            "search": {
                "queries": list(plan.queries),
                "query_results": [
                    {
                        "source": item.source,
                        "query": item.query,
                        "total_matches": item.total_matches,
                        "retrieved_count": item.retrieved_count,
                    }
                    for item in result.query_results
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
                "unresolved_work_count": len(result.unresolved_works),
                "source_failure_count": len(result.failures) + len(related_failures),
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
                    "Classificação preliminar baseada somente nos abstracts."
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


def create_live_retrieval_app(*, project_root: Path | None = None):
    root = project_root or Path(__file__).resolve().parents[2]
    _load_env(root / ".env")
    timeout = float(os.getenv("HTTP_TIMEOUT", "20"))
    email = os.getenv("NCBI_EMAIL") or None
    openalex = OpenAlexClient(
        email=email,
        api_key=os.getenv("OPENALEX_API_KEY") or None,
        timeout=timeout,
    )
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
            OpenAlexSearchProvider(openalex),
            ScieloSearchProvider(openalex),
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
        )
        if os.getenv("GEMINI_API_KEY")
        else None
    )
    runner = RetrievalPreviewRunner(
        engine,
        planner=GenericHealthQueryPlanner(translator),
        abstract_client=pmc_client,
        evidence_analyzer=evidence_analyzer,
        related_client=pubmed_client,
    )
    try:
        document_parser = LiteParseDocumentParser(
            max_pages=int(os.getenv("DOCUMENT_MAX_PAGES", "100")),
            parse_timeout=float(os.getenv("DOCUMENT_PARSE_TIMEOUT", "45")),
        )
    except DocumentParsingError:
        document_parser = None
    service = AnalysisJobService(
        runner,
        result_serializer=lambda result: result,
        article_runner=(
            ArticleFirstAnalysisRunner(
                GeminiArticleExtractor(evidence_analyzer),
                runner,
                PubMedReferenceResolver(pubmed_client, pmc_client),
                document_parser,
            )
            if evidence_analyzer is not None
            else None
        ),
        max_workers=2,
    )
    app = create_app(service, mode_label=RETRIEVAL_MODE_LABEL)
    app.extensions["fatofake_job_service"] = service
    return app
