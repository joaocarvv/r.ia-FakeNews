"""Ficha auditável do artigo enviado, sem preencher ausências por inferência."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Sequence

from .quality_validation import classify_study_design


def _normalized_tokens(value: str) -> set[str]:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return {token for token in re.findall(r"[a-z0-9]+", plain) if len(token) > 1}


def _authors_consistency(
    pubmed_authors: Sequence[str],
    crossref_authors: Sequence[str],
) -> tuple[str, str]:
    if not pubmed_authors or not crossref_authors:
        return "UNKNOWN", "Não há duas listas de autores disponíveis para comparação."
    pubmed_tokens = set().union(*(_normalized_tokens(name) for name in pubmed_authors))
    crossref_tokens = set().union(*(_normalized_tokens(name) for name in crossref_authors))
    overlap = len(pubmed_tokens & crossref_tokens)
    minimum = max(1, min(len(pubmed_tokens), len(crossref_tokens)) // 2)
    if overlap >= minimum:
        return "CONSISTENT", "PubMed e Crossref possuem autores com nomes compatíveis."
    return "REVIEW_REQUIRED", "As listas de autores do PubMed e Crossref exigem revisão."


def _section_signal(
    sections: Sequence[tuple[str, str]],
    keywords: Sequence[str],
    missing_message: str,
) -> dict[str, Any]:
    for title, text in sections:
        normalized = title.casefold()
        if any(keyword in normalized for keyword in keywords):
            excerpt = " ".join(text.split())[:500]
            return {
                "status": "FOUND",
                "section": title,
                "excerpt": excerpt or None,
                "explanation": f"Seção {title!r} localizada no texto disponível.",
            }
    return {
        "status": "NOT_FOUND",
        "section": None,
        "excerpt": None,
        "explanation": missing_message,
    }


def _sample_size(text: str) -> dict[str, Any]:
    patterns = (
        r"\bn\s*=\s*([1-9]\d{1,6})\b",
        r"\bsample of\s+([1-9]\d{1,6})\b",
        r"\benrolled\s+([1-9]\d{1,6})\b",
        r"\b([1-9]\d{1,6})\s+(?:participants|patients|subjects)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return {
                "status": "FOUND",
                "value": int(match.group(1)),
                "source": "EXPLICIT_TEXT",
                "explanation": f"Amostra explícita localizada no texto: {match.group(0)}.",
            }
    return {
        "status": "NOT_FOUND",
        "value": None,
        "source": None,
        "explanation": "Nenhum tamanho de amostra explícito foi localizado automaticamente.",
    }


def build_article_dossier(
    *,
    title: str | None,
    doi: str | None,
    pmid: str | None,
    authors: Sequence[str] = (),
    journal: str | None = None,
    publication_date: str | None = None,
    publication_types: Sequence[str] = (),
    text: str = "",
    sections: Sequence[tuple[str, str]] = (),
    identity: Any | None = None,
    llm_context: str | None = None,
    absolute_language: Sequence[str] = (),
    source_url: str | None = None,
) -> dict[str, Any]:
    """Produz uma ficha factual e marca explicitamente o que não foi confirmado."""

    crossref_authors = tuple(getattr(identity, "crossref_authors", ()) or ())
    author_status, author_explanation = _authors_consistency(authors, crossref_authors)
    identity_status = str(getattr(identity, "status", "UNKNOWN"))
    identity_reason = str(
        getattr(identity, "reason", "Identidade ainda não conferida em fonte externa.")
    )
    crossref_type = getattr(identity, "crossref_work_type", None)
    updates = tuple(getattr(identity, "crossref_updates", ()) or ())
    update_types = {str(getattr(item, "update_type", "")).casefold() for item in updates}
    normalized_types = {item.casefold() for item in publication_types}

    design = classify_study_design(
        title or "",
        text,
        publication_types=publication_types,
        crossref_type=crossref_type,
        llm_context=llm_context,
    )
    protocol_ids = tuple(
        dict.fromkeys(
            match.upper()
            for match in re.findall(r"\b(?:NCT\d{8}|CRD\d{8,}|PROSPERO\s*\d+)\b", text, re.I)
        )
    )
    is_preprint = bool(
        "preprint" in normalized_types
        or str(crossref_type or "").casefold() in {"posted-content", "preprint"}
    )
    is_retracted = bool(
        normalized_types & {"retracted publication", "retraction of publication"}
        or "retraction" in update_types
    )
    corrections = sorted(
        item for item in update_types if item in {"correction", "erratum", "expression-of-concern"}
    )
    if "published erratum" in normalized_types:
        corrections.append("erratum")
    if "expression of concern" in normalized_types:
        corrections.append("expression-of-concern")

    return {
        "identity": {
            "status": identity_status,
            "title": title,
            "doi": doi,
            "pmid": pmid,
            "doi_and_title_consistency": (
                "CONFIRMED" if identity_status == "VERIFIED" else identity_status
            ),
            "authors_consistency": author_status,
            "authors_explanation": author_explanation,
            "explanation": identity_reason,
            "source_url": getattr(identity, "crossref_url", None) or source_url,
        },
        "publication": {
            "authors": list(authors),
            "journal": journal,
            "publication_date": publication_date,
            "publication_types": list(publication_types),
            "crossref_type": crossref_type,
        },
        "editorial_status": {
            "peer_review": "PREPRINT" if is_preprint else "UNKNOWN",
            "peer_review_explanation": (
                "O documento foi identificado como preprint."
                if is_preprint
                else "Indexação e presença em periódico não confirmam revisão por pares."
            ),
            "retraction": "RETRACTED" if is_retracted else "NOT_FOUND",
            "retraction_explanation": (
                "Há sinal explícito de retratação nos metadados consultados."
                if is_retracted
                else "Nenhuma retratação foi localizada; ausência não prova inexistência."
            ),
            "corrections": corrections,
        },
        "methodology": {
            "assessment_status": "NOT_EVALUATED",
            "study_design": design.design.value,
            "classification_source": design.source,
            "classification_explanation": design.rationale,
            "sample_size": _sample_size(text),
            "protocol": {
                "status": "FOUND" if protocol_ids else "NOT_FOUND",
                "identifiers": list(protocol_ids),
                "explanation": (
                    f"Identificadores explícitos localizados: {', '.join(protocol_ids)}."
                    if protocol_ids
                    else "Nenhum identificador de protocolo foi localizado no texto disponível."
                ),
            },
        },
        "transparency": {
            "funding": _section_signal(
                sections,
                ("funding", "financial support", "financiamento"),
                "Seção de financiamento não localizada no texto disponível.",
            ),
            "conflicts_of_interest": _section_signal(
                sections,
                ("conflict", "competing interest", "disclosure"),
                "Seção de conflitos de interesse não localizada no texto disponível.",
            ),
            "data_availability": _section_signal(
                sections,
                ("data availability", "availability of data", "data sharing"),
                "Seção de disponibilidade de dados não localizada no texto disponível.",
            ),
        },
        "language": {
            "absolute_language": list(absolute_language),
            "status": "ALERT" if absolute_language else "NO_AUTOMATIC_ALERT",
        },
        "results_conclusion_consistency": {
            "status": "NOT_EVALUATED",
            "explanation": (
                "A diferença entre resultados e conclusão exige uma comparação semântica "
                "específica e não foi inferida apenas por metadados."
            ),
        },
    }
