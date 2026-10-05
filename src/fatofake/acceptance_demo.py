"""Backend controlado para testar a experiência web sem alegações científicas."""

from __future__ import annotations

import time
import unicodedata
from typing import Any, Mapping

from .analysis_service import AnalysisServiceError
from .api import AnalysisJobService, create_app
from .result_presentation import build_user_summary
from .verification_cards import build_verification_indicators


DEMO_MODE_LABEL = (
    "DEMONSTRAÇÃO CONTROLADA — dados sintéticos; não representa análise científica real"
)


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


class AcceptanceDemoRunner:
    """Produz um contrato completo e explicitamente sintético para avaliação de UX."""

    def __init__(self, *, delay: float = 0.8) -> None:
        self.delay = delay

    def analyze(
        self,
        claim: str,
        article_reference: str | None = None,
    ) -> Mapping[str, Any]:
        normalized = _normalized(claim)
        if "cafe" not in normalized or "prostata" not in normalized:
            raise AnalysisServiceError(
                "Nesta demonstração controlada, informe uma alegação que mencione "
                "café e próstata."
            )
        if self.delay:
            time.sleep(self.delay)

        query = "coffee consumption AND prostate cancer"
        articles = [
            {
                "pmid": "DEMO-001",
                "title": "Artigo controlado A — associação observacional",
                "authors": ["Equipe de demonstração"],
                "journal": "Periódico sintético",
                "publication_date": "2024",
                "doi": None,
                "url": "https://example.org/fatofake/demo-001",
                "access_level": "ABSTRACT_ONLY",
                "pmcid": None,
                "pmc_url": None,
                "quality": {
                    "study_design": "OBSERVATIONAL",
                    "level": "LOW",
                    "is_retracted": False,
                    "rationale": "Perfil sintético criado apenas para testar a interface.",
                    "checks": [],
                    "datasets": [],
                    "trial_registrations": [],
                },
                "assessments": [
                    {
                        "pair_id": "demo-pair-001",
                        "relation": "SUPPORTS",
                        "model_relation": "SUPPORTS",
                        "confidence": 0.78,
                        "margin": 0.62,
                        "probabilities": {
                            "support": 0.78,
                            "contradiction": 0.10,
                            "neutral": 0.12,
                        },
                        "rationale": "Classificação controlada para teste de usabilidade.",
                        "model_name": "controlled-demo",
                        "evidence": {
                            "statement_id": "demo-statement-001",
                            "text": "Trecho sintético: o estudo observou uma associação, mas não demonstrou causalidade.",
                            "section": "Resumo simulado",
                            "pmid": "DEMO-001",
                            "pmcid": None,
                            "doi": None,
                            "source_url": "https://example.org/fatofake/demo-001",
                        },
                    }
                ],
            },
            {
                "pmid": "DEMO-002",
                "title": "Artigo controlado B — resultado sem associação clara",
                "authors": ["Equipe de demonstração"],
                "journal": "Periódico sintético",
                "publication_date": "2023",
                "doi": None,
                "url": "https://example.org/fatofake/demo-002",
                "access_level": "ABSTRACT_ONLY",
                "pmcid": None,
                "pmc_url": None,
                "quality": {
                    "study_design": "OBSERVATIONAL",
                    "level": "UNCLEAR",
                    "is_retracted": False,
                    "rationale": "Perfil sintético criado apenas para testar a interface.",
                    "checks": [],
                    "datasets": [],
                    "trial_registrations": [],
                },
                "assessments": [
                    {
                        "pair_id": "demo-pair-002",
                        "relation": "NEUTRAL",
                        "model_relation": "NEUTRAL",
                        "confidence": 0.71,
                        "margin": 0.43,
                        "probabilities": {
                            "support": 0.15,
                            "contradiction": 0.14,
                            "neutral": 0.71,
                        },
                        "rationale": "Classificação controlada para teste de usabilidade.",
                        "model_name": "controlled-demo",
                        "evidence": {
                            "statement_id": "demo-statement-002",
                            "text": "Trecho sintético: os resultados não permitiram identificar uma associação consistente.",
                            "section": "Resumo simulado",
                            "pmid": "DEMO-002",
                            "pmcid": None,
                            "doi": None,
                            "source_url": "https://example.org/fatofake/demo-002",
                        },
                    }
                ],
            },
        ]
        result = {
            "input": {
                "claim": claim,
                "article_reference": article_reference,
                "reference_type": None,
            },
            "search": {
                "queries": [query],
                "query_results": [
                    {
                        "source": "DEMO_CONTROLADO",
                        "query": query,
                        "total_matches": 2,
                        "retrieved_count": 2,
                    }
                ],
                "candidate_count": 2,
                "unique_work_count": 2,
                "unresolved_work_count": 0,
                "source_failure_count": 0,
            },
            "articles": articles,
            "failures": [],
            "synthesis": {
                "direction": "MIXED",
                "strength": "INSUFFICIENT",
                "article_count": 2,
                "usable_article_count": 2,
                "has_conflict": False,
                "probabilities": {
                    "support": 0.47,
                    "contradiction": 0.12,
                    "neutral": 0.41,
                },
                "rationale": "Resultado sintético para inspecionar a apresentação.",
                "articles": [],
            },
            "report": {
                "conclusion": "INSUFFICIENT_EVIDENCE",
                "headline": "Demonstração: evidência insuficiente",
                "summary": (
                    "Esta resposta usa conteúdo sintético para testar a experiência. "
                    "Nenhuma conclusão científica deve ser extraída dela."
                ),
                "methodology": [],
                "limitations": [
                    "Todos os artigos e trechos desta execução são sintéticos.",
                    "O teste avalia somente navegação, clareza e apresentação do resultado.",
                    "Uma execução científica real ainda depende das fontes externas e dos modelos configurados.",
                ],
                "sources": [
                    {
                        "label": "Fonte controlada A — não científica",
                        "url": "https://example.org/fatofake/demo-001",
                        "pmid": "DEMO-001",
                    },
                    {
                        "label": "Fonte controlada B — não científica",
                        "url": "https://example.org/fatofake/demo-002",
                        "pmid": "DEMO-002",
                    },
                ],
            },
        }
        result["verification"] = {
            "indicators": build_verification_indicators(
                articles=articles,
                research_context="EPIDEMIOLOGICAL",
            ),
            "alerts": [],
        }
        result["user_summary"] = build_user_summary(result)
        return result


def create_acceptance_demo_app(*, delay: float = 0.8):
    runner = AcceptanceDemoRunner(delay=delay)
    service = AnalysisJobService(
        runner,
        result_serializer=lambda result: result,
        max_workers=1,
    )
    app = create_app(service, mode_label=DEMO_MODE_LABEL)
    app.extensions["fatofake_job_service"] = service
    return app
