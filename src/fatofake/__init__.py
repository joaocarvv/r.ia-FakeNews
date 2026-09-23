"""Núcleo da aplicação Fato ou Fake."""

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
from .pubmed import (
    Publication,
    PubMedClient,
    PubMedError,
    PubMedSearchResult,
    QueryResult,
    search_pubmed,
)

__all__ = [
    "AnalysisInput",
    "ArticleContent",
    "ContentRetrievalError",
    "ContentSection",
    "CrossrefClient",
    "CrossrefError",
    "CrossrefNotFoundError",
    "CrossrefWork",
    "IdentityVerification",
    "InputValidationError",
    "PmcClient",
    "Publication",
    "PubMedClient",
    "PubMedError",
    "PubMedSearchResult",
    "QueryPlanner",
    "QueryResult",
    "SearchPlan",
    "SearchPreparationError",
    "prepare_search_plan",
    "retrieve_article_content",
    "search_pubmed",
    "validate_analysis_input",
    "verify_publication_identity",
    "verify_publications",
]
