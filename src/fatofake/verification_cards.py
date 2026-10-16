"""Monta indicadores transparentes para os cards da aplicação."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

_ABSOLUTE_LANGUAGE = (
    r"\b100\s*%",
    r"\bsempre\b",
    r"\bnunca\b",
    r"\bcomprovad[oa]s?\b",
    r"\bgarant(?:e|ido|ida)\b",
    r"\bcura\b",
    r"\belimina\b",
    r"\bsem risco\b",
)


def _percentage(numerator: int, denominator: int) -> int | None:
    if denominator <= 0:
        return None
    return round(100 * numerator / denominator)


def build_verification_confidence(
    *,
    articles: Sequence[dict[str, Any]],
    research_context: str,
) -> dict[str, Any]:
    """Índice de cobertura da checagem; não estima probabilidade de verdade."""

    total = len(articles)
    assessed_articles = tuple(item for item in articles if item.get("assessments"))
    assessed = len(assessed_articles)
    usable = sum(
        any(
            assessment.get("relation") in {"SUPPORTS", "CONTRADICTS"}
            for assessment in item.get("assessments", ())
        )
        for item in assessed_articles
    )
    contextual = sum(
        any(assessment.get("relation") == "NEUTRAL" for assessment in item.get("assessments", ()))
        for item in assessed_articles
    )
    current_year = datetime.now(timezone.utc).year
    years: list[int] = []
    citation_total = 0
    known_citations = 0
    network_total = 0
    known_network = 0
    sources: set[str] = set()
    for item in assessed_articles:
        match = re.search(r"\b(?:19|20)\d{2}\b", str(item.get("publication_date") or ""))
        if match:
            years.append(int(match.group(0)))
        retrieval = item.get("retrieval") or {}
        sources.update(str(source) for source in retrieval.get("sources") or ())
        citations = retrieval.get("citation_count")
        if citations is not None:
            citation_total += max(0, int(citations))
            known_citations += 1
        related = retrieval.get("related_work_count")
        if related is not None:
            network_total += max(0, int(related))
            known_network += 1

    recent_ratio = (
        sum(year >= current_year - 10 for year in years) / len(years) if years else 0
    )
    components = [
        {
            "code": "ANALYSIS_COVERAGE",
            "label": "Cobertura dos textos",
            "points": round(30 * assessed / total, 1) if total else 0.0,
            "maximum": 30,
            "detail": f"{assessed} de {total} artigos tiveram abstract analisado.",
            "status": "AVAILABLE" if total else "MISSING",
        },
        {
            "code": "INDEPENDENT_EVIDENCE",
            "label": "Volume de evidência independente",
            "points": min(20.0, usable * 4.0),
            "maximum": 20,
            "detail": (
                f"{usable} artigo(s) compararam diretamente a alegação; "
                f"{contextual} forneceram apenas contexto relacionado."
            ),
            "status": "AVAILABLE" if usable else "MISSING",
        },
        {
            "code": "RECENCY",
            "label": "Atualidade das publicações",
            "points": round(15 * recent_ratio, 1),
            "maximum": 15,
            "detail": f"{len(years)} publicação(ões) tinham ano identificável.",
            "status": "AVAILABLE" if years else "MISSING",
        },
        {
            "code": "CITATIONS",
            "label": "Contexto de citações",
            "points": min(15.0, round(math.log10(1 + citation_total) * 5, 1)),
            "maximum": 15,
            "detail": (
                f"{citation_total} citação(ões) registradas em {known_citations} artigo(s)."
                if known_citations
                else "Contagens de citações não foram recuperadas."
            ),
            "status": "AVAILABLE" if known_citations else "MISSING",
        },
        {
            "code": "RESEARCH_NETWORK",
            "label": "Ramificação e diversidade",
            "points": min(10.0, len(sources) * 2.0 + min(network_total, 20) * 0.2),
            "maximum": 10,
            "detail": (
                f"{len(sources)} fonte(s); ramificações conhecidas para {known_network} artigo(s)."
            ),
            "status": "AVAILABLE" if sources else "MISSING",
        },
    ]
    clinical_applicable = research_context == "CLINICAL"
    trial_component = {
        "code": "CLINICAL_TRIALS",
        "label": "Ensaios clínicos",
        "points": 0.0,
        "maximum": 10,
        "detail": (
            "Aplicável, mas registros e resultados ainda não foram confirmados."
            if clinical_applicable
            else "Não aplicável ao desenho identificado para o artigo."
        ),
        "status": "MISSING" if clinical_applicable else "NOT_APPLICABLE",
    }
    components.append(trial_component)
    applicable = [item for item in components if item["status"] != "NOT_APPLICABLE"]
    maximum = sum(float(item["maximum"]) for item in applicable)
    points = sum(float(item["points"]) for item in applicable)
    score = round(100 * points / maximum) if maximum else 0
    level = "HIGH" if score >= 75 else "MODERATE" if score >= 50 else "LOW"
    return {
        "score": score,
        "level": level,
        "label": "confiança da verificação",
        "explanation": (
            "Mede quanto da checagem foi coberto por dados recuperados. "
            "Não é a probabilidade de o artigo estar correto."
        ),
        "components": components,
    }


def detect_language_alerts(claim: str) -> list[dict[str, Any]]:
    """Detecta somente padrões explícitos; não tenta julgar a alegação."""

    matches = [
        match.group(0)
        for pattern in _ABSOLUTE_LANGUAGE
        if (match := re.search(pattern, claim, flags=re.IGNORECASE))
    ]
    if not matches:
        return []
    return [
        {
            "code": "ABSOLUTE_LANGUAGE",
            "severity": "WARNING",
            "title": "Uso de linguagem absoluta",
            "detail": (
                "A alegação contém expressão absoluta: "
                + ", ".join(dict.fromkeys(matches))
                + ". Esse padrão exige evidência especialmente forte."
            ),
            "source_url": None,
        }
    ]


def build_unassessed_cards(
    *,
    claim: str,
    article_reference: str | None,
    retrieved_article_count: int,
) -> dict[str, Any]:
    """Contrato seguro para a etapa que recupera metadados, mas não lê conteúdo."""

    alerts = detect_language_alerts(claim)
    alerts.append(
        {
            "code": "CONTENT_NOT_ANALYZED",
            "severity": "INFO",
            "title": "Conteúdo científico ainda não analisado",
            "detail": (
                "Os artigos foram recuperados, mas seus resultados ainda não foram "
                "comparados com a alegação."
            ),
            "source_url": None,
        }
    )
    if article_reference:
        alerts.append(
            {
                "code": "PEER_REVIEW_NOT_VERIFIED",
                "severity": "INFO",
                "title": "Revisão por pares não confirmada",
                "detail": (
                    "A referência foi recebida, mas o status editorial ainda não foi "
                    "confirmado em uma fonte independente."
                ),
                "source_url": None,
            }
        )
    else:
        alerts.append(
            {
                "code": "NO_ARTICLE_SUBMITTED",
                "severity": "INFO",
                "title": "Nenhum artigo específico foi enviado",
                "detail": "A execução avaliou somente a alegação informada pelo usuário.",
                "source_url": None,
            }
        )

    return {
        "partial_verification": {
            "status": "NOT_EVALUATED",
            "percentage": None,
            "verified_count": 0,
            "total_count": retrieved_article_count,
            "explanation": (
                f"{retrieved_article_count} artigo(s) foram recuperados, mas nenhum "
                "teve o conteúdo analisado nesta etapa."
            ),
        },
        "meta_analysis": {
            "status": "NOT_EVALUATED",
            "compatibility_percentage": None,
            "compatible_count": 0,
            "compared_count": 0,
            "study_count": 0,
            "explanation": "Meta-análises ainda não foram identificadas e comparadas.",
        },
        "clinical_trials": {
            "status": "NOT_EVALUATED",
            "registration_percentage": None,
            "registered_count": 0,
            "eligible_count": 0,
            "with_results_count": 0,
            "explanation": "Registros de ensaios clínicos ainda não foram conferidos.",
        },
        "alerts": alerts,
    }


def build_abstract_analysis_cards(
    *,
    claim: str,
    article_reference: str | None,
    retrieved_article_count: int,
    assessments: Sequence[Any],
    content_failure_count: int = 0,
) -> dict[str, Any]:
    """Resume a análise de abstracts sem alegar validação de texto completo."""

    assessed = tuple(assessments)
    meta = tuple(
        item
        for item in assessed
        if item.study_design == "SYSTEMATIC_REVIEW_META_ANALYSIS"
    )
    comparable_meta = tuple(
        item for item in meta if item.relation in {"SUPPORTS", "CONTRADICTS"}
    )
    compatible_meta = sum(item.relation == "SUPPORTS" for item in comparable_meta)
    identified_trials = sum(
        item.study_design == "RANDOMIZED_CLINICAL_TRIAL" for item in assessed
    )
    alerts = detect_language_alerts(claim)
    alerts.append(
        {
            "code": "ABSTRACT_ONLY_ANALYSIS",
            "severity": "INFO",
            "title": "Análise limitada aos abstracts",
            "detail": (
                "A compatibilidade foi estimada a partir dos resumos. Métodos, "
                "tabelas e resultados completos ainda não foram verificados."
            ),
            "source_url": None,
        }
    )
    if article_reference:
        alerts.append(
            {
                "code": "PEER_REVIEW_NOT_VERIFIED",
                "severity": "INFO",
                "title": "Revisão por pares não confirmada",
                "detail": (
                    "O status editorial da referência enviada ainda precisa ser "
                    "confirmado em uma fonte independente."
                ),
                "source_url": None,
            }
        )
    else:
        alerts.append(
            {
                "code": "NO_ARTICLE_SUBMITTED",
                "severity": "INFO",
                "title": "Nenhum artigo específico foi enviado",
                "detail": "A execução avaliou somente a alegação informada pelo usuário.",
                "source_url": None,
            }
        )
    if content_failure_count:
        alerts.append(
            {
                "code": "ABSTRACT_RETRIEVAL_FAILURES",
                "severity": "WARNING",
                "title": "Alguns abstracts não puderam ser obtidos",
                "detail": f"Falha na recuperação de {content_failure_count} abstract(s).",
                "source_url": None,
            }
        )

    return {
        "partial_verification": {
            "status": "AVAILABLE" if assessed else "NOT_EVALUATED",
            "percentage": _percentage(len(assessed), retrieved_article_count),
            "verified_count": len(assessed),
            "total_count": retrieved_article_count,
            "explanation": (
                f"{len(assessed)} de {retrieved_article_count} artigo(s) recuperados "
                "tiveram o abstract analisado. Este percentual mede cobertura, não verdade."
            ),
        },
        "meta_analysis": {
            "status": "AVAILABLE" if comparable_meta else "NOT_FOUND",
            "compatibility_percentage": _percentage(
                compatible_meta, len(comparable_meta)
            ),
            "compatible_count": compatible_meta,
            "compared_count": len(comparable_meta),
            "study_count": len(meta),
            "not_comparable_count": len(meta) - len(comparable_meta),
            "explanation": (
                f"{len(comparable_meta)} meta-análise(s) foram comparadas; "
                f"{compatible_meta} apresentaram resultado compatível no abstract. "
                f"{len(meta) - len(comparable_meta)} não responderam diretamente à alegação."
                if comparable_meta
                else "Nenhuma meta-análise comparável foi identificada nos abstracts."
            ),
        },
        "clinical_trials": {
            "status": "NOT_EVALUATED",
            "registration_percentage": None,
            "registered_count": 0,
            "eligible_count": identified_trials,
            "with_results_count": 0,
            "explanation": (
                f"{identified_trials} possível(is) ensaio(s) foram identificados, mas "
                "os registros do ClinicalTrials.gov ainda não foram conferidos."
                if identified_trials
                else "Nenhum ensaio clínico foi identificado; o ClinicalTrials.gov ainda não foi consultado."
            ),
        },
        "alerts": alerts,
    }


def build_analysis_cards(analysis: Any) -> dict[str, Any]:
    """Deriva cards somente de resultados já produzidos pelo pipeline científico."""

    articles = tuple(analysis.articles)
    failures = tuple(analysis.failures)
    attempted = len(articles) + len(failures)
    usable_pmids = {
        item.pmid
        for item in analysis.synthesis.articles
        if item.uncertain_count < item.assessment_count
    }
    coverage = _percentage(len(usable_pmids), attempted)

    directions = {
        item.pmid: item.direction.value for item in analysis.synthesis.articles
    }
    meta_articles = tuple(
        item
        for item in articles
        if item.quality_report.study_design.value
        == "SYSTEMATIC_REVIEW_META_ANALYSIS"
    )
    comparable_meta = tuple(
        item
        for item in meta_articles
        if item.publication.pmid in usable_pmids
        and directions.get(item.publication.pmid) in {"SUPPORTS", "CONTRADICTS"}
    )
    compatible_meta = sum(
        directions.get(item.publication.pmid) == "SUPPORTS"
        for item in comparable_meta
    )

    trial_articles = tuple(
        item
        for item in articles
        if item.quality_report.study_design.value == "RANDOMIZED_CLINICAL_TRIAL"
    )
    registered_trials = tuple(
        item
        for item in trial_articles
        if item.quality_report.trial_registrations
    )
    trials_with_results = sum(
        any(trial.has_results for trial in item.quality_report.trial_registrations)
        for item in registered_trials
    )

    alerts = detect_language_alerts(analysis.analysis_input.claim)
    if not analysis.analysis_input.article_reference:
        alerts.append(
            {
                "code": "NO_ARTICLE_SUBMITTED",
                "severity": "INFO",
                "title": "Nenhum artigo específico foi enviado",
                "detail": "A execução avaliou somente a alegação informada pelo usuário.",
                "source_url": None,
            }
        )
    else:
        alerts.append(
            {
                "code": "PEER_REVIEW_NOT_VERIFIED",
                "severity": "INFO",
                "title": "Revisão por pares não confirmada",
                "detail": (
                    "Indexação e metadados não comprovam, sozinhos, que o artigo "
                    "passou por revisão por pares."
                ),
                "source_url": None,
            }
        )
    for item in articles:
        if item.quality_report.is_retracted:
            alerts.append(
                {
                    "code": "RETRACTED_ARTICLE",
                    "severity": "CRITICAL",
                    "title": "Retratação identificada",
                    "detail": f"O artigo PMID {item.publication.pmid} possui retratação confirmada.",
                    "source_url": item.publication.url,
                }
            )
    if failures:
        stages = Counter(item.stage for item in failures)
        alerts.append(
            {
                "code": "PROCESSING_FAILURES",
                "severity": "WARNING",
                "title": "Parte dos artigos não pôde ser processada",
                "detail": ", ".join(
                    f"{count} em {stage}" for stage, count in sorted(stages.items())
                ),
                "source_url": None,
            }
        )

    return {
        "partial_verification": {
            "status": "AVAILABLE" if usable_pmids else "NOT_EVALUATED",
            "percentage": coverage,
            "verified_count": len(usable_pmids),
            "total_count": attempted,
            "explanation": (
                f"{len(usable_pmids)} de {attempted} artigo(s) tentados forneceram "
                "evidência textual utilizável. Este percentual mede cobertura, não verdade."
            ),
        },
        "meta_analysis": {
            "status": "AVAILABLE" if comparable_meta else "NOT_FOUND",
            "compatibility_percentage": _percentage(
                compatible_meta, len(comparable_meta)
            ),
            "compatible_count": compatible_meta,
            "compared_count": len(comparable_meta),
            "study_count": len(meta_articles),
            "not_comparable_count": len(meta_articles) - len(comparable_meta),
            "explanation": (
                f"{len(comparable_meta)} meta-análise(s) puderam ser comparadas; "
                f"{compatible_meta} apresentaram sinal compatível."
                if comparable_meta
                else "Nenhuma meta-análise comparável foi identificada."
            ),
        },
        "clinical_trials": {
            "status": "AVAILABLE" if trial_articles else "NOT_FOUND",
            "registration_percentage": _percentage(
                len(registered_trials), len(trial_articles)
            ),
            "registered_count": len(registered_trials),
            "eligible_count": len(trial_articles),
            "with_results_count": trials_with_results,
            "explanation": (
                f"{len(registered_trials)} de {len(trial_articles)} ensaio(s) clínico(s) "
                f"possuem registro localizado; {trials_with_results} informam resultados."
                if trial_articles
                else "Nenhum ensaio clínico randomizado foi identificado."
            ),
        },
        "alerts": alerts,
    }
