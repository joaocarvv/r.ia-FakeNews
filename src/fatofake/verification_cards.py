"""Monta indicadores transparentes para os cards da aplicação."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Sequence


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


def _article_relation(article: dict[str, Any]) -> str:
    relations = {
        str(item.get("relation") or "UNCERTAIN").upper()
        for item in article.get("assessments") or ()
    }
    if "SUPPORTS" in relations and "CONTRADICTS" in relations:
        return "MIXED"
    if "CONTRADICTS" in relations:
        return "CONTRADICTS"
    if "SUPPORTS" in relations:
        return "SUPPORTS"
    if "NEUTRAL" in relations:
        return "CONTEXT_ONLY"
    return "INCONCLUSIVE"


def build_verification_indicators(
    *,
    articles: Sequence[dict[str, Any]],
    research_context: str,
) -> dict[str, Any]:
    """Separa cobertura, direção das evidências e qualidade metodológica."""

    total = len(articles)
    assessed_articles = tuple(item for item in articles if item.get("assessments"))
    assessed = len(assessed_articles)
    relations = Counter(_article_relation(item) for item in assessed_articles)
    direct = relations["SUPPORTS"] + relations["CONTRADICTS"] + relations["MIXED"]
    full_text_assessed = sum(
        str(item.get("access_level") or "")
        in {"FULL_TEXT", "OPEN_ACCESS_FULL_TEXT", "LOCAL_PDF_FULL_TEXT"}
        for item in assessed_articles
    )

    if not total:
        coverage_status = "NOT_AVAILABLE"
        coverage_label = "Busca sem documentos recuperados"
    elif not assessed:
        coverage_status = "NOT_ASSESSED"
        coverage_label = "Documentos recuperados, mas ainda não analisados"
    elif assessed < total:
        coverage_status = "PARTIAL"
        coverage_label = "Cobertura parcial dos documentos recuperados"
    elif full_text_assessed == assessed:
        coverage_status = "FULL_TEXT"
        coverage_label = "Todos os documentos analisados com texto completo"
    else:
        coverage_status = "ABSTRACT_INCLUDED"
        coverage_label = "Todos analisados, com uso de abstracts"

    if relations["MIXED"] or (relations["SUPPORTS"] and relations["CONTRADICTS"]):
        compatibility_status = "DIVERGENT"
        compatibility_label = "Evidências divergentes"
    elif relations["SUPPORTS"]:
        compatibility_status = "COMPATIBLE"
        compatibility_label = "Compatível com as evidências recuperadas"
    elif relations["CONTRADICTS"]:
        compatibility_status = "POTENTIAL_INCOMPATIBILITY"
        compatibility_label = "Possível incompatibilidade"
    elif relations["CONTEXT_ONLY"]:
        compatibility_status = "CONTEXT_ONLY"
        compatibility_label = "Somente contexto relacionado"
    else:
        compatibility_status = "NOT_COMPARABLE"
        compatibility_label = "Não foi possível comparar"

    quality_counts: Counter[str] = Counter()
    study_design_counts: Counter[str] = Counter()
    retracted_count = 0
    registered_protocol_count = 0
    data_available_count = 0
    for article in assessed_articles:
        quality = article.get("quality") or {}
        level = str(quality.get("level") or "UNKNOWN").upper()
        if level == "UNCLEAR":
            level = "UNKNOWN"
        if level not in {"HIGH", "MODERATE", "LOW", "UNKNOWN"}:
            level = "UNKNOWN"
        quality_counts[level] += 1
        study_design = str(quality.get("study_design") or "UNKNOWN").upper()
        study_design_counts[study_design] += 1
        retracted_count += bool(quality.get("is_retracted"))
        registered_protocol_count += bool(quality.get("trial_registrations"))
        data_available_count += bool(quality.get("datasets"))

    known_levels = {
        level for level in ("HIGH", "MODERATE", "LOW") if quality_counts[level]
    }
    if retracted_count:
        methodological_level = "CRITICAL_ALERT"
        methodological_label = "Alerta grave: há artigo retratado"
    elif not known_levels:
        methodological_level = "UNKNOWN"
        methodological_label = "Confiança metodológica desconhecida"
    elif len(known_levels) == 1 and not quality_counts["UNKNOWN"]:
        methodological_level = next(iter(known_levels))
        methodological_label = {
            "HIGH": "Confiança metodológica alta",
            "MODERATE": "Confiança metodológica moderada",
            "LOW": "Confiança metodológica baixa",
        }[methodological_level]
    else:
        methodological_level = "MIXED"
        methodological_label = "Confiança metodológica heterogênea"

    return {
        "search_coverage": {
            "status": coverage_status,
            "label": coverage_label,
            "retrieved_count": total,
            "assessed_count": assessed,
            "directly_comparable_count": direct,
            "full_text_count": full_text_assessed,
            "abstract_only_count": assessed - full_text_assessed,
            "explanation": (
                f"{assessed} de {total} documentos recuperados foram analisados; "
                f"{full_text_assessed} com texto completo e {direct} responderam "
                "diretamente à alegação."
            ),
        },
        "evidence_compatibility": {
            "status": compatibility_status,
            "label": compatibility_label,
            "supporting_count": relations["SUPPORTS"],
            "contradicting_count": relations["CONTRADICTS"],
            "mixed_count": relations["MIXED"],
            "context_only_count": relations["CONTEXT_ONLY"],
            "inconclusive_count": relations["INCONCLUSIVE"],
            "compared_article_count": assessed,
            "explanation": (
                f"Entre {assessed} artigos analisados: {relations['SUPPORTS']} compatíveis, "
                f"{relations['CONTRADICTS']} divergentes, {relations['MIXED']} mistos, "
                f"{relations['CONTEXT_ONLY']} apenas contextuais e "
                f"{relations['INCONCLUSIVE']} inconclusivos."
            ),
        },
        "methodological_confidence": {
            "level": methodological_level,
            "label": methodological_label,
            "assessed_article_count": assessed,
            "quality_counts": {
                "HIGH": quality_counts["HIGH"],
                "MODERATE": quality_counts["MODERATE"],
                "LOW": quality_counts["LOW"],
                "UNKNOWN": quality_counts["UNKNOWN"],
            },
            "study_design_counts": dict(sorted(study_design_counts.items())),
            "retracted_count": retracted_count,
            "registered_protocol_count": registered_protocol_count,
            "data_available_count": data_available_count,
            "clinical_registration_applicable": research_context == "CLINICAL",
            "explanation": (
                f"Qualidade informada para {assessed} artigos: "
                f"{quality_counts['HIGH']} alta, {quality_counts['MODERATE']} moderada, "
                f"{quality_counts['LOW']} baixa e {quality_counts['UNKNOWN']} desconhecida; "
                f"{registered_protocol_count} com protocolo localizado, "
                f"{data_available_count} com dados associados e {retracted_count} retratados. "
                "Citações e ramificações não alteram esta classificação."
            ),
        },
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
        "indicators": build_verification_indicators(
            articles=tuple(
                {"assessments": [], "quality": {}}
                for _index in range(retrieved_article_count)
            ),
            research_context="UNKNOWN",
        ),
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
    """Resume os trechos analisados e explicita seu nível de acesso."""

    assessed = tuple(assessments)
    full_text_count = sum(
        getattr(item, "content_scope", "ABSTRACT")
        in {"FULL_TEXT", "OPEN_ACCESS_FULL_TEXT"}
        for item in assessed
    )
    abstract_count = len(assessed) - full_text_count
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
            "code": "CONTENT_SCOPE",
            "severity": "INFO",
            "title": "Escopo dos textos analisados",
            "detail": (
                f"{full_text_count} artigo(s) foram analisados com texto completo e "
                f"{abstract_count} somente pelo abstract. Cada trecho informa seção "
                "e página quando a fonte fornece paginação."
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
                "code": "CONTENT_RETRIEVAL_FAILURES",
                "severity": "WARNING",
                "title": "Alguns textos não puderam ser obtidos",
                "detail": f"Falha na recuperação de {content_failure_count} conteúdo(s).",
                "source_url": None,
            }
        )

    return {
        "indicators": build_verification_indicators(
            articles=tuple(
                {
                    "access_level": getattr(item, "content_scope", "ABSTRACT_ONLY"),
                    "assessments": [{"relation": item.relation}],
                    "quality": {
                        "level": "UNKNOWN",
                        "study_design": item.study_design,
                        "is_retracted": False,
                        "trial_registrations": [],
                        "datasets": [],
                    },
                }
                for item in assessed
            )
            + tuple(
                {"assessments": [], "quality": {}}
                for _index in range(max(0, retrieved_article_count - len(assessed)))
            ),
            research_context="UNKNOWN",
        ),
        "partial_verification": {
            "status": "AVAILABLE" if assessed else "NOT_EVALUATED",
            "percentage": _percentage(len(assessed), retrieved_article_count),
            "verified_count": len(assessed),
            "total_count": retrieved_article_count,
            "full_text_count": full_text_count,
            "abstract_only_count": abstract_count,
            "full_text_percentage": _percentage(full_text_count, len(assessed)),
            "explanation": (
                f"{len(assessed)} de {retrieved_article_count} artigo(s) recuperados "
                "tiveram trechos analisados. Este percentual mede cobertura, não verdade."
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
                f"{compatible_meta} apresentaram resultado compatível nos trechos. "
                f"{len(meta) - len(comparable_meta)} não responderam diretamente à alegação."
                if comparable_meta
                else "Nenhuma meta-análise comparável foi identificada nos trechos analisados."
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

    indicator_articles = tuple(
        {
            "access_level": getattr(
                getattr(item, "content", None), "access_level", "UNKNOWN"
            ),
            "assessments": [
                {"relation": assessment.relation.value}
                for assessment in getattr(item, "assessments", ())
            ],
            "quality": {
                "level": getattr(
                    getattr(item.quality_report, "quality_level", None),
                    "value",
                    "UNKNOWN",
                ),
                "study_design": item.quality_report.study_design.value,
                "is_retracted": item.quality_report.is_retracted,
                "trial_registrations": list(
                    getattr(item.quality_report, "trial_registrations", ())
                ),
                "datasets": list(getattr(item.quality_report, "datasets", ())),
            },
        }
        for item in articles
    ) + tuple(
        {"assessments": [], "quality": {}}
        for _failure in failures
    )

    return {
        "indicators": build_verification_indicators(
            articles=indicator_articles,
            research_context="UNKNOWN",
        ),
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
