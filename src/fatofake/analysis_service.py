"""Orquestra a análise de uma alegação em múltiplos artigos independentes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .chunking import ChunkingConfig, ChunkingError, chunk_article_content
from .crossref import CrossrefClient
from .evidence_classification import (
    ClassificationConfig,
    EvidenceAssessment,
    NliClassifier,
    classify_claim_evidence_pairs,
)
from .evidence_extraction import (
    ExtractionConfig,
    build_claim_evidence_pairs,
    extract_evidence_statements,
)
from .evidence_synthesis import CorpusSynthesis, synthesize_evidence
from .federated_search import FederatedSearchEngine, FederatedSearchResult
from .hybrid_retrieval import HybridConfig, HybridIndex
from .input_validation import AnalysisInput, validate_analysis_input
from .pmc import (
    ArticleContent,
    ContentRetrievalError,
    PmcClient,
    retrieve_article_content,
)
from .pubmed import (
    PubMedClient,
    PubMedSearchResult,
    Publication,
    search_pubmed,
)
from .quality_validation import (
    ArticleQualityReport,
    ClinicalTrialsClient,
    DataCiteClient,
    validate_article_quality,
)
from .report_generation import (
    EvidenceReport,
    MethodologySummary,
    ReportSource,
    generate_evidence_report,
)
from .retrieval import Bm25Config, Bm25Index, RetrievalError
from .search_preparation import QueryPlanner, SearchPlan, prepare_search_plan
from .semantic_retrieval import EmbeddingEncoder, SemanticIndex
from .retrieval_backend import ChunkIndexFactory


class AnalysisServiceError(RuntimeError):
    """O serviço não conseguiu reunir artigos suficientes para uma análise."""


class ArticleProcessingError(RuntimeError):
    """Uma etapa conhecida falhou durante o processamento de um artigo."""

    def __init__(self, pmid: str, stage: str, message: str) -> None:
        self.pmid = pmid
        self.stage = stage
        super().__init__(message)


@dataclass(frozen=True)
class MultiArticleAnalysisConfig:
    """Limites explícitos para uma análise multiartigo limitada e reproduzível."""

    max_results_per_query: int = 5
    target_articles: int = 3
    minimum_successful_articles: int = 2

    def __post_init__(self) -> None:
        if not 1 <= self.max_results_per_query <= 100:
            raise RetrievalError("max_results_per_query deve estar entre 1 e 100.")
        if self.target_articles < 2:
            raise RetrievalError("target_articles deve ser ao menos 2.")
        if not 2 <= self.minimum_successful_articles <= self.target_articles:
            raise RetrievalError(
                "minimum_successful_articles deve estar entre 2 e target_articles."
            )


@dataclass(frozen=True)
class ArticleEvidenceBundle:
    """Resultados de um artigo prontos para entrar na síntese entre estudos."""

    publication: Publication
    content: ArticleContent
    assessments: tuple[EvidenceAssessment, ...]
    quality_report: ArticleQualityReport

    def __post_init__(self) -> None:
        pmids = {
            self.publication.pmid,
            self.content.pmid,
            self.quality_report.pmid,
            *(item.evidence.pmid for item in self.assessments),
        }
        if len(pmids) != 1:
            raise RetrievalError("O pacote combina resultados de artigos diferentes.")
        if not self.assessments:
            raise RetrievalError("O artigo precisa de ao menos uma evidência classificada.")


@dataclass(frozen=True)
class ArticleAnalysisFailure:
    pmid: str
    title: str
    stage: str
    reason: str


@dataclass(frozen=True)
class MultiArticleAnalysis:
    analysis_input: AnalysisInput
    search_plan: SearchPlan
    search_result: PubMedSearchResult | FederatedSearchResult
    articles: tuple[ArticleEvidenceBundle, ...]
    failures: tuple[ArticleAnalysisFailure, ...]
    synthesis: CorpusSynthesis
    report: EvidenceReport


class ArticleProcessor(Protocol):
    def process(self, publication: Publication, claim: str) -> ArticleEvidenceBundle: ...


class ScientificArticleProcessor:
    """Executa conteúdo, recuperação, NLI e qualidade para uma publicação."""

    def __init__(
        self,
        *,
        pmc_client: PmcClient,
        embedding_encoder: EmbeddingEncoder,
        nli_classifier: NliClassifier,
        crossref_client: CrossrefClient,
        datacite_client: DataCiteClient,
        clinical_trials_client: ClinicalTrialsClient,
        chunking_config: ChunkingConfig | None = None,
        bm25_config: Bm25Config | None = None,
        hybrid_config: HybridConfig | None = None,
        extraction_config: ExtractionConfig | None = None,
        classification_config: ClassificationConfig | None = None,
        hybrid_top_k: int = 8,
        vector_store: ChunkIndexFactory | None = None,
    ) -> None:
        if hybrid_top_k < 1:
            raise RetrievalError("hybrid_top_k deve ser maior que zero.")
        self.pmc_client = pmc_client
        self.embedding_encoder = embedding_encoder
        self.vector_store = vector_store
        self.nli_classifier = nli_classifier
        self.crossref_client = crossref_client
        self.datacite_client = datacite_client
        self.clinical_trials_client = clinical_trials_client
        self.chunking_config = chunking_config or ChunkingConfig(
            max_words=120, overlap_words=20
        )
        self.bm25_config = bm25_config
        self.hybrid_config = hybrid_config
        self.extraction_config = extraction_config or ExtractionConfig(
            max_statements=6,
            max_per_chunk=2,
            min_words=8,
            max_words=80,
        )
        self.classification_config = classification_config or ClassificationConfig(
            minimum_confidence=0.60,
            minimum_margin=0.10,
        )
        self.hybrid_top_k = hybrid_top_k

    def process(self, publication: Publication, claim: str) -> ArticleEvidenceBundle:
        stage = "content_retrieval"
        try:
            content = retrieve_article_content(publication, self.pmc_client)
            stage = "chunking"
            chunks = chunk_article_content(content, self.chunking_config)
            stage = "hybrid_retrieval"
            lexical_index = Bm25Index(chunks, self.bm25_config)
            semantic_index = (self.vector_store.index(chunks) if self.vector_store is not None
                              else SemanticIndex(chunks, self.embedding_encoder))
            ranked_chunks = HybridIndex(
                lexical_index,
                semantic_index,
                self.hybrid_config,
            ).search(claim, top_k=self.hybrid_top_k)
            stage = "evidence_extraction"
            statements = extract_evidence_statements(
                claim,
                ranked_chunks,
                self.extraction_config,
            )
            pairs = build_claim_evidence_pairs(claim, statements)
            stage = "relation_classification"
            assessments = classify_claim_evidence_pairs(
                pairs,
                self.nli_classifier,
                self.classification_config,
            )
            stage = "quality_validation"
            quality_report = validate_article_quality(
                publication,
                content,
                self.crossref_client,
                self.datacite_client,
                self.clinical_trials_client,
            )
        except (ChunkingError, ContentRetrievalError, RetrievalError) as error:
            raise ArticleProcessingError(
                publication.pmid,
                stage,
                str(error),
            ) from error

        return ArticleEvidenceBundle(
            publication=publication,
            content=content,
            assessments=assessments,
            quality_report=quality_report,
        )


class MultiArticleAnalysisService:
    """Busca candidatos, processa artigos independentes e produz um relatório."""

    def __init__(
        self,
        *,
        query_planner: QueryPlanner,
        article_processor: ArticleProcessor,
        pubmed_client: PubMedClient | None = None,
        search_engine: FederatedSearchEngine | None = None,
        config: MultiArticleAnalysisConfig | None = None,
    ) -> None:
        self.query_planner = query_planner
        if pubmed_client is None and search_engine is None:
            raise RetrievalError(
                "Informe pubmed_client ou search_engine para executar a busca."
            )
        if pubmed_client is not None and search_engine is not None:
            raise RetrievalError(
                "Informe somente pubmed_client ou search_engine, não ambos."
            )
        self.pubmed_client = pubmed_client
        self.search_engine = search_engine
        self.article_processor = article_processor
        self.config = config or MultiArticleAnalysisConfig()

    def analyze(
        self,
        claim: str,
        article_reference: str | None = None,
    ) -> MultiArticleAnalysis:
        analysis_input = validate_analysis_input(claim, article_reference)
        search_plan = prepare_search_plan(analysis_input, self.query_planner)
        if self.search_engine is not None:
            search_result = self.search_engine.search(
                search_plan,
                max_results_per_query=self.config.max_results_per_query,
            )
        else:
            assert self.pubmed_client is not None
            search_result = search_pubmed(
                search_plan,
                self.pubmed_client,
                max_results_per_query=self.config.max_results_per_query,
            )

        articles: list[ArticleEvidenceBundle] = []
        failures: list[ArticleAnalysisFailure] = []
        for publication in search_result.publications:
            if len(articles) == self.config.target_articles:
                break
            try:
                bundle = self.article_processor.process(publication, analysis_input.claim)
            except ArticleProcessingError as error:
                failures.append(
                    ArticleAnalysisFailure(
                        pmid=publication.pmid,
                        title=publication.title,
                        stage=error.stage,
                        reason=str(error),
                    )
                )
                continue
            if bundle.publication.pmid != publication.pmid:
                raise AnalysisServiceError(
                    "O processador retornou resultados de outro artigo."
                )
            if bundle.quality_report.is_retracted:
                failures.append(
                    ArticleAnalysisFailure(
                        pmid=publication.pmid,
                        title=publication.title,
                        stage="eligibility",
                        reason=(
                            "Artigo com retratação confirmada; excluído da síntese "
                            "científica."
                        ),
                    )
                )
                continue
            articles.append(bundle)

        if len(articles) < self.config.minimum_successful_articles:
            raise AnalysisServiceError(
                "A busca não produziu artigos processáveis suficientes: "
                f"{len(articles)} obtido(s), mínimo de "
                f"{self.config.minimum_successful_articles}."
            )

        assessments = tuple(
            assessment
            for article in articles
            for assessment in article.assessments
        )
        profiles = tuple(
            article.quality_report.to_quality_profile(article.publication)
            for article in articles
        )
        synthesis = synthesize_evidence(assessments, profiles)

        methodology = tuple(
            MethodologySummary(
                pmid=article.publication.pmid,
                instrument="módulo de validação externa",
                confidence=article.quality_report.quality_level.value,
                quality_level=article.quality_report.quality_level,
                critical_flaws=(),
                single_reviewer=False,
                rationale=article.quality_report.rationale,
                applicability_note=(
                    "Perfil preliminar: ainda é necessária uma avaliação estruturada "
                    "de risco de viés adequada ao desenho do estudo."
                ),
                source_url=article.publication.url,
            )
            for article in articles
        )
        sources: list[ReportSource] = []
        for article in articles:
            publication = article.publication
            sources.append(
                ReportSource(
                    label=f"PMID {publication.pmid}: {publication.title}",
                    url=publication.url,
                    pmid=publication.pmid,
                )
            )
            if article.content.pmc_url:
                sources.append(
                    ReportSource(
                        label=f"Texto completo do PMID {publication.pmid}",
                        url=article.content.pmc_url,
                    )
                )
            if publication.doi:
                sources.append(
                    ReportSource(
                        label=f"DOI do PMID {publication.pmid}",
                        url=f"https://doi.org/{publication.doi}",
                    )
                )

        limitations = [
            (
                "A busca é limitada aos primeiros "
                f"{self.config.max_results_per_query} resultados por consulta e não "
                "constitui revisão sistemática."
            ),
            (
                "Os perfis de qualidade são preliminares e não substituem uma "
                "avaliação humana de risco de viés."
            ),
        ]
        if isinstance(search_result, FederatedSearchResult):
            if search_result.unresolved_works:
                limitations.append(
                    f"{len(search_result.unresolved_works)} trabalho(s) recuperado(s) "
                    "fora do PubMed ainda não possuem PMID e, por isso, não puderam "
                    "seguir para a recuperação de conteúdo no fluxo atual."
                )
            if search_result.failures:
                limitations.append(
                    f"{len(search_result.failures)} consulta(s) a fontes federadas "
                    "falharam isoladamente; as demais fontes continuaram a busca."
                )
        if failures:
            limitations.append(
                f"{len(failures)} artigo(s) candidato(s) falharam durante o "
                "processamento e não entraram na síntese."
            )
        report = generate_evidence_report(
            analysis_input.claim,
            synthesis,
            methodology,
            sources,
            additional_limitations=limitations,
        )
        return MultiArticleAnalysis(
            analysis_input=analysis_input,
            search_plan=search_plan,
            search_result=search_result,
            articles=tuple(articles),
            failures=tuple(failures),
            synthesis=synthesis,
            report=report,
        )
