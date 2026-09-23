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
    "CrossrefClient",
    "CrossrefError",
    "CrossrefNotFoundError",
    "CrossrefWork",
    "IdentityVerification",
    "InputValidationError",
    "Publication",
    "PubMedClient",
    "PubMedError",
    "PubMedSearchResult",
    "QueryPlanner",
    "QueryResult",
    "SearchPlan",
    "SearchPreparationError",
    "prepare_search_plan",
    "search_pubmed",
    "validate_analysis_input",
    "verify_publication_identity",
    "verify_publications",
]
