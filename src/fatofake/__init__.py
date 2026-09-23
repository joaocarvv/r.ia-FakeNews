"""Núcleo da aplicação Fato ou Fake."""

from .input_validation import AnalysisInput, InputValidationError, validate_analysis_input
from .search_preparation import (
    QueryPlanner,
    SearchPlan,
    SearchPreparationError,
    prepare_search_plan,
)

__all__ = [
    "AnalysisInput",
    "InputValidationError",
    "QueryPlanner",
    "SearchPlan",
    "SearchPreparationError",
    "prepare_search_plan",
    "validate_analysis_input",
]
