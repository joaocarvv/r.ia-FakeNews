"""Prepara a entrada validada para a etapa de busca científica."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Sequence

from .input_validation import AnalysisInput


MAX_SEARCH_QUERIES = 3
MAX_QUERY_LENGTH = 300


class SearchPreparationError(ValueError):
    """Erro ao transformar uma alegação em um plano de busca."""


class QueryPlanner(Protocol):
    """Contrato para componentes que geram consultas a partir de uma alegação."""

    def generate_queries(self, claim: str) -> Sequence[str]: ...


@dataclass(frozen=True)
class SearchPlan:
    """Plano normalizado que será consumido pelos conectores científicos."""

    claim: str
    queries: tuple[str, ...]
    article_reference: str | None = None


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def prepare_search_plan(analysis_input: AnalysisInput, planner: QueryPlanner) -> SearchPlan:
    """Gera e valida consultas sem avaliar a veracidade da alegação."""

    generated_queries = planner.generate_queries(analysis_input.claim)
    if isinstance(generated_queries, (str, bytes)):
        raise SearchPreparationError("O planejador deve retornar uma sequência de consultas.")

    unique_queries: list[str] = []
    seen: set[str] = set()
    for generated_query in generated_queries:
        if not isinstance(generated_query, str):
            raise SearchPreparationError("Cada consulta deve ser informada como texto.")

        normalized_query = _normalize_query(generated_query)
        if not normalized_query:
            continue
        if len(normalized_query) > MAX_QUERY_LENGTH:
            raise SearchPreparationError(
                f"Cada consulta deve ter no máximo {MAX_QUERY_LENGTH} caracteres."
            )

        comparison_key = normalized_query.casefold()
        if comparison_key not in seen:
            seen.add(comparison_key)
            unique_queries.append(normalized_query)

    if not unique_queries:
        raise SearchPreparationError("O planejador não produziu nenhuma consulta válida.")
    if len(unique_queries) > MAX_SEARCH_QUERIES:
        raise SearchPreparationError(
            f"O plano deve conter no máximo {MAX_SEARCH_QUERIES} consultas."
        )

    return SearchPlan(
        claim=analysis_input.claim,
        queries=tuple(unique_queries),
        article_reference=analysis_input.article_reference,
    )
