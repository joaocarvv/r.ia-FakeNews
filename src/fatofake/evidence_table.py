"""Tabela de evidências padronizada e síntese ponderada, sem votação simples."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


DESIGN_WEIGHTS = {
    "SYSTEMATIC_REVIEW_META_ANALYSIS": 1.0,
    "RANDOMIZED_CLINICAL_TRIAL": 0.85,
    "OBSERVATIONAL": 0.55,
    "OTHER": 0.3,
    "UNKNOWN": 0.25,
    "NOT_ASSESSED": 0.0,
}
DESIGN_LABELS = {
    "SYSTEMATIC_REVIEW_META_ANALYSIS": "Revisão sistemática/meta-análise",
    "RANDOMIZED_CLINICAL_TRIAL": "Ensaio clínico randomizado",
    "OBSERVATIONAL": "Estudo observacional",
    "OTHER": "Outro desenho",
    "UNKNOWN": "Desenho não identificado",
    "NOT_ASSESSED": "Não avaliado",
}
COMPARABILITY_WEIGHTS = {"DIRECT": 1.0, "PARTIAL": 0.6, "INDIRECT": 0.3}
COMPARABILITY_LABELS = {
    "DIRECT": "Comparação direta",
    "PARTIAL": "Parcialmente comparável",
    "INDIRECT": "Indireta",
}
ROB_WEIGHTS = {
    "LOW": 1.0,
    "SOME_CONCERNS": 0.75,
    "UNCLEAR": 0.6,
    "HIGH": 0.45,
    "CRITICAL": 0.2,
}
ROB_LABELS = {
    "LOW": "Baixo risco de viés",
    "SOME_CONCERNS": "Algumas preocupações",
    "UNCLEAR": "Risco de viés incerto",
    "HIGH": "Alto risco de viés",
    "CRITICAL": "Risco crítico de viés",
}
ROB_TOOL_LABELS = {
    "ROB2": "RoB 2",
    "ROBINS_I": "ROBINS-I",
    "AMSTAR2": "AMSTAR 2",
    "NOT_APPLICABLE": "Não se aplica",
}
ACCESS_WEIGHTS = {
    "FULL_TEXT": 1.0,
    "OPEN_ACCESS_FULL_TEXT": 1.0,
    "USER_PROVIDED_FULL_TEXT": 1.0,
    "ABSTRACT_ONLY": 0.8,
    "ABSTRACT": 0.8,
}
EDITORIAL_WEIGHTS = {
    "RETRACTED": 0.0,
    "EXPRESSION_OF_CONCERN": 0.5,
    "PREPRINT": 0.6,
    "CORRECTED": 1.0,
    "PUBLISHED": 1.0,
    "UNKNOWN": 1.0,
}
CERTAINTY_LABELS = {
    "HIGH": "Alta",
    "MODERATE": "Moderada",
    "LOW": "Baixa",
    "VERY_LOW": "Muito baixa",
}


def _year(value: Any) -> int | None:
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def _duplicate_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def editorial_status(article: Mapping[str, Any]) -> str:
    explicit = str(article.get("editorial_status") or "").upper()
    if explicit in EDITORIAL_WEIGHTS:
        return explicit
    quality = article.get("quality") or {}
    if quality.get("is_retracted"):
        return "RETRACTED"
    types = " ".join(article.get("publication_types") or ()).casefold()
    if "retracted publication" in types or "retraction of publication" in types:
        return "RETRACTED"
    if "preprint" in types:
        return "PREPRINT"
    return "UNKNOWN"


_EMPTY_VALUES = {"não informado", "nao informado", "não relatado", "n/a", "na", "-"}


def _clean_row(study_row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (None if isinstance(value, str) and value.strip().casefold() in _EMPTY_VALUES else value)
        for key, value in study_row.items()
    }


_EXPOSURE_TYPES = {"THERAPEUTIC", "PREVENTIVE", "CAUSAL", "ASSOCIATION", "DIAGNOSTIC"}


def _term_present(term: str, text: str) -> bool:
    """Casa variações simples (hospitalization/hospitalized) pelo prefixo das palavras."""

    words = re.findall(r"[a-z0-9]+", term.casefold())
    return bool(words) and all(
        re.search(r"\b" + re.escape(word[: max(4, min(len(word), 6))]), text) for word in words
    )


def concept_coverage(
    article: Mapping[str, Any], concept_groups: Sequence[Sequence[str]]
) -> list[bool]:
    """Quais conceitos da alegação aparecem no que foi lido do estudo."""

    text = " ".join(
        [
            str(article.get("title") or ""),
            str(article.get("abstract") or ""),
            *(str(item.get("text") or "") for item in article.get("analyzed_passages") or ()),
        ]
    ).casefold()
    return [any(_term_present(term, text) for term in group) for group in concept_groups]


def _checked_comparability(
    comparability: str | None,
    coverage: list[bool],
    claim_type: str | None,
) -> tuple[str | None, str | None]:
    """O modelo às vezes chama de DIRECT um estudo de outra intervenção; o texto decide."""

    if comparability is None or not coverage:
        return comparability, None
    if claim_type in _EXPOSURE_TYPES and not coverage[0]:
        return "INDIRECT", "A intervenção/exposição da alegação não aparece no texto lido do estudo."
    missing = coverage.count(False)
    if missing and comparability == "DIRECT":
        downgraded = "PARTIAL" if missing / len(coverage) < 0.5 else "INDIRECT"
        return downgraded, f"{missing} de {len(coverage)} conceito(s) da alegação não aparecem no texto lido."
    if missing / len(coverage) >= 0.5 and comparability == "PARTIAL":
        return "INDIRECT", f"{missing} de {len(coverage)} conceito(s) da alegação não aparecem no texto lido."
    return comparability, None


def build_evidence_rows(
    articles: Sequence[Mapping[str, Any]],
    claim_profile: Mapping[str, Any] | None = None,
    submitted_population: Sequence[str] = (),
) -> list[dict[str, Any]]:
    concept_groups = [list(group) for group in (claim_profile or {}).get("concept_groups") or ()]
    claim_type = (claim_profile or {}).get("claim_type")
    rows: list[dict[str, Any]] = []
    for article in articles:
        assessments = article.get("assessments") or ()
        assessment = assessments[0] if assessments else None
        study_row = _clean_row(dict((assessment or {}).get("study_row") or {}))
        evidence = (assessment or {}).get("evidence") or {}
        design = str((article.get("quality") or {}).get("study_design") or "NOT_ASSESSED")
        relation = (assessment or {}).get("relation") or "NOT_ASSESSED"
        comparability = study_row.get("comparability") or ("INDIRECT" if assessment else None)
        model_comparability = comparability
        coverage = concept_coverage(article, concept_groups) if assessment and concept_groups else []
        comparability, comparability_check = _checked_comparability(
            comparability, coverage, claim_type
        )
        rob = study_row.get("rob_overall") or "UNCLEAR"
        access = str(article.get("access_level") or "METADATA_ONLY")
        status = editorial_status(article)
        factors = {
            "design": DESIGN_WEIGHTS.get(design, 0.25),
            "comparability": COMPARABILITY_WEIGHTS.get(comparability or "", 0.0),
            "risk_of_bias": ROB_WEIGHTS.get(rob, 0.6),
            "access": ACCESS_WEIGHTS.get(access, 0.8 if assessment else 0.0),
            "editorial": EDITORIAL_WEIGHTS.get(status, 1.0),
        }
        weight = 0.0
        if assessment and relation != "UNCERTAIN":
            weight = 1.0
            for value in factors.values():
                weight *= value
        rows.append(
            {
                "pmid": article.get("pmid"),
                "doi": article.get("doi"),
                "url": article.get("url"),
                "title": article.get("title"),
                "title_pt": study_row.get("title_pt") or None,
                "journal": article.get("journal"),
                "year": _year(article.get("publication_date")),
                "publication_date": article.get("publication_date"),
                "relation": relation,
                "assessed": assessment is not None,
                "design": design,
                "design_label": DESIGN_LABELS.get(design, design),
                "design_detail": study_row.get("design_detail") or None,
                "population": study_row.get("population") or None,
                "sample_size": study_row.get("sample_size") or None,
                "intervention_or_exposure": study_row.get("intervention_or_exposure") or None,
                "comparator": study_row.get("comparator") or None,
                "outcome": study_row.get("outcome") or None,
                "effect_estimate": study_row.get("effect_estimate") or None,
                "finding_pt": study_row.get("finding_pt") or None,
                "quote": evidence.get("text"),
                "quote_pt": study_row.get("quote_pt") or None,
                "quote_section": evidence.get("section"),
                "quote_page": evidence.get("page"),
                "rationale": (assessment or {}).get("rationale"),
                "comparability": comparability,
                "comparability_label": COMPARABILITY_LABELS.get(comparability or "", None),
                "comparability_notes": study_row.get("comparability_notes") or None,
                "comparability_check": comparability_check,
                "model_comparability": model_comparability,
                "concept_coverage": coverage,
                "rob_tool": study_row.get("rob_tool") or None,
                "rob_tool_label": ROB_TOOL_LABELS.get(study_row.get("rob_tool") or "", None),
                "rob_overall": rob if assessment else None,
                "rob_label": ROB_LABELS.get(rob) if assessment else None,
                "rob_domains": list(study_row.get("rob_domains") or ()),
                "registration_ids": list(study_row.get("registration_ids") or ()),
                "cohort_or_dataset": study_row.get("cohort_or_dataset") or None,
                "access_level": access,
                "full_text_source": article.get("full_text_source"),
                "full_text_attempts": list(article.get("full_text_attempts") or ()),
                "pmc_url": article.get("pmc_url"),
                "work_key": article.get("work_key")
                or article.get("pmid")
                or (f"doi:{article['doi']}" if article.get("doi") else None),
                "editorial_status": status,
                "weight_factors": factors,
                "weight": round(weight, 3),
                "duplicate_group": None,
                "same_population_as_submitted": False,
                "sources": list((article.get("retrieval") or {}).get("sources") or ()),
            }
        )
    _mark_duplicate_populations(rows, submitted_population)
    return rows


def _population_keys(row: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    keys = [("registro", item) for item in row.get("registration_ids") or ()]
    if row.get("cohort_or_dataset"):
        keys.append(("coorte", row["cohort_or_dataset"]))
    return [
        (_duplicate_key(value), kind, value)
        for kind, value in keys
        if len(_duplicate_key(value)) >= 4
    ]


def _mark_duplicate_populations(
    rows: list[dict[str, Any]],
    submitted_population: Sequence[str] = (),
) -> None:
    """Estudos da mesma população dividem um peso; os do artigo enviado não pesam.

    Registro e nome de coorte do mesmo estudo são unidos quando algum trabalho
    cita os dois (união de conjuntos), para não contar o mesmo ensaio duas vezes.
    """

    parent: dict[str, str] = {}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    labels: dict[str, str] = {}
    row_keys: list[list[str]] = []
    for row in rows:
        keys = _population_keys(row)
        row_keys.append([key for key, _kind, _value in keys])
        for key, kind, value in keys:
            labels.setdefault(key, f"{kind} {value}")
            find(key)
        for key, _kind, _value in keys[1:]:
            parent[find(key)] = find(keys[0][0])

    submitted_roots = {
        find(_duplicate_key(value))
        for value in submitted_population
        if len(_duplicate_key(value)) >= 4 and _duplicate_key(value) in parent
    }
    groups: dict[str, list[int]] = {}
    for index, keys in enumerate(row_keys):
        for root in dict.fromkeys(find(key) for key in keys):
            groups.setdefault(root, [])
            if index not in groups[root]:
                groups[root].append(index)

    for root, members in groups.items():
        member_labels = sorted(
            {labels[key] for key in labels if find(key) == root}
        )
        label = " = ".join(member_labels)
        if root in submitted_roots:
            for index in members:
                row = rows[index]
                row["duplicate_group"] = label
                row["same_population_as_submitted"] = True
                row["weight"] = 0.0
                row["weight_factors"]["independence"] = 0.0
            continue
        weighted = [index for index in members if rows[index]["weight"] > 0]
        if len(members) < 2 or len(weighted) < 2:
            if len(members) >= 2:
                for index in members:
                    rows[index]["duplicate_group"] = rows[index]["duplicate_group"] or label
            continue
        for index in members:
            row = rows[index]
            if row["duplicate_group"] is None:
                row["duplicate_group"] = label
                row["weight"] = round(row["weight"] / len(weighted), 3)
                row["weight_factors"]["shared_population"] = round(1 / len(weighted), 3)


_LEVELS = ("VERY_LOW", "LOW", "MODERATE", "HIGH")


def _is_randomized_evidence(row: Mapping[str, Any]) -> bool:
    if row["design"] == "RANDOMIZED_CLINICAL_TRIAL":
        return True
    if row["design"] != "SYSTEMATIC_REVIEW_META_ANALYSIS":
        return False
    detail = str(row.get("design_detail") or "").casefold()
    # Revisão de estudos observacionais começa baixa, como os próprios estudos.
    return not any(term in detail for term in ("observ", "coorte", "cohort", "caso-controle", "case-control", "transvers", "cross-sectional"))


def _certainty(
    direct_rows: Sequence[Mapping[str, Any]],
    supports: float,
    contradicts: float,
) -> tuple[str, list[str]]:
    """Aproximação do GRADE: ponto de partida pelo desenho e rebaixamentos."""

    total = supports + contradicts
    if not direct_rows or total <= 0:
        return "VERY_LOW", ["Sem estudos diretos com peso."]
    weight = lambda rows: sum(row["weight"] for row in rows)
    randomized_share = weight([row for row in direct_rows if _is_randomized_evidence(row)]) / total
    level = 3 if randomized_share >= 0.5 else 1
    reasons = [
        "Parte de certeza alta: a maior parte do peso vem de ensaios randomizados."
        if level == 3
        else "Parte de certeza baixa: a maior parte do peso vem de estudos observacionais."
    ]
    bias_share = weight([row for row in direct_rows if row.get("rob_overall") in {"HIGH", "CRITICAL", "UNCLEAR"}]) / total
    if bias_share > 0.5:
        level -= 1
        reasons.append("Rebaixada por risco de viés alto ou incerto na maior parte do peso.")
    if min(supports, contradicts) / total > 0.25:
        level -= 1
        reasons.append("Rebaixada por inconsistência: estudos em direções opostas.")
    indirect_share = weight([row for row in direct_rows if row.get("comparability") != "DIRECT"]) / total
    if indirect_share > 0.5:
        level -= 1
        reasons.append("Rebaixada por evidência indireta: a maior parte não compara exatamente o mesmo PICO.")
    if len(direct_rows) < 3 or total < 0.9:
        level -= 1
        reasons.append("Rebaixada por imprecisão: poucos estudos ou pouco peso.")
    return _LEVELS[max(0, min(3, level))], reasons


def synthesize_evidence(
    articles: Sequence[Mapping[str, Any]],
    *,
    candidate_count: int,
    claim_profile: Mapping[str, Any] | None = None,
    submitted_population: Sequence[str] = (),
    analysis_unavailable: bool = False,
    sources: Sequence[str] = (),
    queries: Sequence[str] = (),
) -> dict[str, Any]:
    rows = build_evidence_rows(articles, claim_profile, submitted_population)
    supports = sum(row["weight"] for row in rows if row["relation"] == "SUPPORTS")
    contradicts = sum(row["weight"] for row in rows if row["relation"] == "CONTRADICTS")
    neutral = sum(row["weight"] for row in rows if row["relation"] == "NEUTRAL")
    direct_rows = [
        row for row in rows if row["relation"] in {"SUPPORTS", "CONTRADICTS"} and row["weight"] > 0
    ]
    direct_weight = supports + contradicts
    certainty, certainty_reasons = _certainty(direct_rows, supports, contradicts)
    if analysis_unavailable and not any(row["assessed"] for row in rows):
        code, label = "ANALYSIS_UNAVAILABLE", "Análise indisponível nesta execução"
        explanation = (
            "Os estudos foram encontrados, mas o modelo de avaliação não respondeu. "
            "Isso não indica ausência de evidência: tente a investigação novamente."
        )
    elif direct_weight == 0:
        code, label = "NO_DIRECT_EVIDENCE", "Sem evidência direta sobre a alegação"
        explanation = (
            "Nenhum estudo avaliado respondeu diretamente à alegação com peso "
            "metodológico suficiente."
        )
    else:
        share = max(supports, contradicts) / direct_weight
        if share >= 0.75 and supports > contradicts:
            code, label = "WEIGHTED_SUPPORT", "A literatura ponderada sustenta a alegação"
        elif share >= 0.75:
            code, label = "WEIGHTED_AGAINST", "A literatura ponderada contradiz a alegação"
        else:
            code, label = "WEIGHTED_CONFLICT", "A literatura ponderada está dividida"
        explanation = (
            f"Peso favorável {supports:.2f} contra {contradicts:.2f} desfavorável, "
            f"somando {len(direct_rows)} estudo(s) com comparação direta ou parcial. "
            "Cada estudo pesa conforme desenho, comparabilidade com a alegação, risco "
            "de viés, acesso ao texto e situação editorial; estudos da mesma população "
            "dividem um único peso."
        )
    same_population = [row for row in rows if row.get("same_population_as_submitted")]
    if same_population:
        explanation += (
            f" {len(same_population)} estudo(s) da mesma população do artigo enviado "
            "foram excluídos do peso: não são confirmação independente."
        )
    retracted = [row for row in rows if row["editorial_status"] == "RETRACTED"]
    if retracted:
        explanation += f" {len(retracted)} estudo(s) retratado(s) foram excluídos do peso."

    assessed = sum(row["assessed"] for row in rows)
    source_text = ", ".join(sources) or "as bases configuradas"
    if candidate_count == 0:
        absence = {
            "code": "NOT_FOUND",
            "message": (
                f"Nenhum estudo foi encontrado em {source_text} com as consultas usadas. "
                "Isso significa “não encontrado”, não “não existe”: a evidência pode "
                "estar em bases não consultadas, em outro idioma, sob outros termos ou "
                "ainda não publicada."
            ),
        }
    elif not direct_rows:
        absence = {
            "code": "FOUND_NOT_ANSWERED",
            "message": (
                f"Foram encontrados {candidate_count} candidato(s) e {assessed} lido(s), "
                "mas nenhum respondeu diretamente à alegação. Ausência de evidência "
                "direta aqui não é evidência de ausência do efeito."
            ),
        }
    else:
        absence = {
            "code": "EVIDENCE_FOUND",
            "message": (
                "A busca não é exaustiva: estudos relevantes podem não ter sido "
                "recuperados ou lidos nesta execução."
            ),
        }

    years = [row["year"] for row in rows if row["year"]]
    return {
        "rows": rows,
        "weighted": {
            "supports": round(supports, 3),
            "contradicts": round(contradicts, 3),
            "neutral": round(neutral, 3),
            "direct_study_count": len(direct_rows),
        },
        "verdict": {
            "code": code,
            "label": label,
            "certainty": certainty,
            "certainty_label": CERTAINTY_LABELS[certainty],
            "certainty_reasons": certainty_reasons,
            "explanation": explanation,
        },
        "absence": absence,
        "duplicate_groups": sorted(
            {row["duplicate_group"] for row in rows if row["duplicate_group"]}
        ),
        "timeline": {
            "first_year": min(years) if years else None,
            "last_year": max(years) if years else None,
        },
        "queries": list(queries),
        "method": (
            "Peso = desenho × comparabilidade PICO × risco de viés × acesso ao texto × "
            "situação editorial. Não é votação: um ensaio direto de baixo risco vale "
            "mais que vários estudos indiretos."
        ),
    }
