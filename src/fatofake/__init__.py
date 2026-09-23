"""Núcleo da aplicação Fato ou Fake."""

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
]
