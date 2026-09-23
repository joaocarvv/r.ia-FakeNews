"""Núcleo da aplicação Fato ou Fake."""

from .input_validation import AnalysisInput, InputValidationError, validate_analysis_input

__all__ = [
    "AnalysisInput",
    "InputValidationError",
    "validate_analysis_input",
]
