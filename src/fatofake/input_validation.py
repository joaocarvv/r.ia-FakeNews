"""Validação e normalização da entrada principal do MVP."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


MIN_CLAIM_LENGTH = 8
MAX_CLAIM_LENGTH = 800
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
DOI_PREFIX_PATTERN = re.compile(
    r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)",
    re.IGNORECASE,
)


class InputValidationError(ValueError):
    """Erro de entrada que pode ser apresentado ao usuário."""


@dataclass(frozen=True)
class AnalysisInput:
    """Entrada normalizada de uma análise."""

    claim: str
    article_reference: str | None = None
    reference_type: str | None = None


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_article_reference(reference: str | None) -> tuple[str | None, str | None]:
    if reference is None or not reference.strip():
        return None, None

    normalized = reference.strip()
    possible_doi = DOI_PREFIX_PATTERN.sub("", normalized).strip()
    if DOI_PATTERN.fullmatch(possible_doi):
        return possible_doi, "doi"

    parsed_url = urlparse(normalized)
    if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
        return normalized, "url"

    raise InputValidationError("Informe um DOI ou uma URL HTTP(S) válida para o artigo.")


def validate_analysis_input(claim: str, article_reference: str | None = None) -> AnalysisInput:
    """Valida e normaliza a alegação e a referência opcional de artigo."""

    if not isinstance(claim, str):
        raise InputValidationError("A alegação deve ser informada como texto.")

    normalized_claim = _normalize_whitespace(claim)
    if len(normalized_claim) < MIN_CLAIM_LENGTH:
        raise InputValidationError(
            f"Informe uma alegação com pelo menos {MIN_CLAIM_LENGTH} caracteres."
        )
    if len(normalized_claim) > MAX_CLAIM_LENGTH:
        raise InputValidationError(
            f"A alegação deve ter no máximo {MAX_CLAIM_LENGTH} caracteres."
        )

    normalized_reference, reference_type = _normalize_article_reference(article_reference)
    return AnalysisInput(normalized_claim, normalized_reference, reference_type)
