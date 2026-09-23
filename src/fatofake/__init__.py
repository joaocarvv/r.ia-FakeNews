"""Núcleo da aplicação Fato ou Fake."""

from .chunking import (
    ChunkingConfig,
    ChunkingError,
    EvidenceChunk,
    chunk_article_content,
)
from .crossref import (
    CrossrefClient,
    CrossrefError,
    CrossrefNotFoundError,
    CrossrefWork,
    IdentityVerification,
    verify_publication_identity,
    verify_publications,
)
from .input_validation import AnalysisInput, InputValidationError, validate_analysis_input
from .pmc import (
    ArticleContent,
    ContentRetrievalError,
    ContentSection,
    PmcClient,
    retrieve_article_content,
)
from .search_preparation import (
    QueryPlanner,
    SearchPlan,
    SearchPreparationError,
    prepare_search_plan,
)
from .semantic_retrieval import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingEncoder,
    SemanticIndex,
    SemanticRetrievedChunk,
    SentenceTransformerEncoder,
)
from .pubmed import (
    Publication,
    PubMedClient,
    PubMedError,
    PubMedSearchResult,
    QueryResult,
    search_pubmed,
)
from .retrieval import (
    Bm25Config,
    Bm25Index,
    RetrievalError,
    RetrievedChunk,
    tokenize,
)

__all__ = [
    "AnalysisInput",
    "ArticleContent",
    "Bm25Config",
    "Bm25Index",
    "ChunkingConfig",
    "ChunkingError",
    "ContentRetrievalError",
    "ContentSection",
    "CrossrefClient",
    "CrossrefError",
    "CrossrefNotFoundError",
    "CrossrefWork",
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingEncoder",
    "EvidenceChunk",
    "IdentityVerification",
    "InputValidationError",
    "PmcClient",
    "Publication",
    "PubMedClient",
    "PubMedError",
    "PubMedSearchResult",
    "QueryPlanner",
    "QueryResult",
    "RetrievalError",
    "RetrievedChunk",
    "SearchPlan",
    "SearchPreparationError",
    "SemanticIndex",
    "SemanticRetrievedChunk",
    "SentenceTransformerEncoder",
    "prepare_search_plan",
    "chunk_article_content",
    "retrieve_article_content",
    "search_pubmed",
    "tokenize",
    "validate_analysis_input",
    "verify_publication_identity",
    "verify_publications",
]
