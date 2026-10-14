"""Modos de pesquisa externa e estimativa de tempo/custo antes de executá-los."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchDepth:
    code: str
    label: str
    description: str
    max_queries: int
    max_results_per_query: int
    max_analysis_articles: int
    # Médias observadas por alegação; servem só para orientar o usuário.
    seconds_per_claim: tuple[int, int]
    input_tokens_per_claim: int
    output_tokens_per_claim: int


SEARCH_DEPTHS: dict[str, SearchDepth] = {
    "QUICK": SearchDepth(
        code="QUICK",
        label="Busca rápida",
        description="Até 5 estudos lidos por alegação, consultas principais.",
        max_queries=6,
        max_results_per_query=5,
        max_analysis_articles=5,
        seconds_per_claim=(45, 120),
        input_tokens_per_claim=14_000,
        output_tokens_per_claim=4_000,
    ),
    "DEEP": SearchDepth(
        code="DEEP",
        label="Revisão profunda",
        description=(
            "Até 15 estudos lidos por alegação, mais consultas, citações e "
            "referências do artigo."
        ),
        max_queries=10,
        max_results_per_query=12,
        max_analysis_articles=15,
        seconds_per_claim=(150, 420),
        input_tokens_per_claim=42_000,
        output_tokens_per_claim=12_000,
    ),
}


def _price(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def research_estimates(model_name: str | None = None) -> dict[str, Any]:
    """Estimativa por alegação; a interface multiplica pelo número selecionado."""

    input_price = _price("GEMINI_INPUT_PRICE_PER_MILLION_USD", 0.10)
    output_price = _price("GEMINI_OUTPUT_PRICE_PER_MILLION_USD", 0.40)
    modes = {}
    for code, depth in SEARCH_DEPTHS.items():
        cost = (
            depth.input_tokens_per_claim * input_price
            + depth.output_tokens_per_claim * output_price
        ) / 1_000_000
        modes[code] = {
            "code": code,
            "label": depth.label,
            "description": depth.description,
            "max_analysis_articles": depth.max_analysis_articles,
            "seconds_per_claim": list(depth.seconds_per_claim),
            "tokens_per_claim": (
                depth.input_tokens_per_claim + depth.output_tokens_per_claim
            ),
            "cost_usd_per_claim": round(cost, 5),
        }
    return {
        "model_name": model_name,
        "pricing_basis": (
            f"US$ {input_price:.2f}/M tokens de entrada e US$ {output_price:.2f}/M de "
            "saída (ajustável por variável de ambiente); valores aproximados."
        ),
        "modes": modes,
    }
