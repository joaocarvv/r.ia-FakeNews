"""Transforma a saída técnica em uma narrativa curta e coerente para o usuário."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


_RELATION_LABELS = {
    "SUPPORTS": "Compatível",
    "CONTRADICTS": "Divergente",
    "NEUTRAL": "Apenas contexto",
    "UNCERTAIN": "Inconclusivo",
}
_SCOPE_LABELS = {
    "FULL_TEXT": "texto completo",
    "OPEN_ACCESS_FULL_TEXT": "texto completo aberto",
    "LOCAL_PDF_FULL_TEXT": "PDF completo enviado",
    "ABSTRACT_ONLY": "somente abstract",
    "ABSTRACT": "somente abstract",
    "METADATA_ONLY": "somente metadados",
    "GEMINI_URL_CONTEXT": "conteúdo acessado pelo modelo",
    "UNKNOWN": "escopo não identificado",
}


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def _count_phrase(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _assessment_rows(
    articles: Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    rows: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for article in articles:
        for assessment in article.get("assessments") or ():
            if isinstance(assessment, Mapping):
                rows.append((article, assessment))
    return rows


def _headline(counts: Mapping[str, int]) -> tuple[str, str]:
    supports = counts["SUPPORTS"]
    contradicts = counts["CONTRADICTS"]
    if supports and contradicts:
        return "MIXED", "Os estudos recuperados apresentam resultados divergentes"
    if supports:
        return "PREDOMINANTLY_COMPATIBLE", "Há compatibilidade preliminar com a literatura recuperada"
    if contradicts:
        return "POTENTIAL_DIVERGENCE", "Foram encontradas divergências em relação ao artigo"
    return "NO_DIRECT_COMPARISON", "Ainda não há evidência direta suficiente para comparar"


def _interpretation(status: str, direct_count: int, abstract_count: int) -> str:
    messages = {
        "MIXED": (
            "Os trabalhos não apontam todos na mesma direção. Isso pede leitura das "
            "diferenças de população, método e desfecho antes de qualquer conclusão."
        ),
        "PREDOMINANTLY_COMPATIBLE": (
            "Os trechos localizados caminham na mesma direção da alegação, mas isso "
            "não comprova que o artigo esteja correto nem elimina limitações metodológicas."
        ),
        "POTENTIAL_DIVERGENCE": (
            "Ao menos um trecho independente aponta em direção diferente da alegação. "
            "Isso é um sinal para investigação, não uma classificação automática de fake news."
        ),
        "NO_DIRECT_COMPARISON": (
            "Os textos recuperados não responderam diretamente à alegação ou não puderam "
            "ser citados com segurança. O sistema deve se abster de confirmar ou negar."
        ),
    }
    result = messages[status]
    if direct_count == 1:
        result += " A direção observada depende de apenas um artigo comparável."
    if abstract_count:
        result += " Parte da leitura foi limitada ao abstract."
    return result


def _finding(
    article: Mapping[str, Any], assessment: Mapping[str, Any]
) -> dict[str, Any]:
    evidence = assessment.get("evidence") or {}
    section = str(evidence.get("section") or "Seção não identificada")
    page = evidence.get("page")
    location = (
        f"Seção {section}, página {page}"
        if page is not None
        else f"Seção {section}; fonte sem paginação"
    )
    relation = str(assessment.get("relation") or "UNCERTAIN").upper()
    scope = str(evidence.get("content_scope") or article.get("access_level") or "UNKNOWN")
    return {
        "relation": relation,
        "relation_label": _RELATION_LABELS.get(relation, "Inconclusivo"),
        "article_title": article.get("title") or "Artigo sem título",
        "publication_date": article.get("publication_date"),
        "study_design": (article.get("quality") or {}).get("study_design"),
        "quote": evidence.get("text"),
        "location": location,
        "scope": scope,
        "scope_label": _SCOPE_LABELS.get(scope, scope.replace("_", " ").lower()),
        "source_url": evidence.get("source_url") or article.get("url"),
        "confidence": assessment.get("confidence"),
    }


def build_user_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    """Cria uma leitura orientada a decisão sem alterar os dados científicos brutos."""

    articles = tuple(
        article
        for article in (result.get("articles") or ())
        if isinstance(article, Mapping)
    )
    rows = _assessment_rows(articles)
    counts = {
        relation: sum(
            str(assessment.get("relation") or "UNCERTAIN").upper() == relation
            for _article, assessment in rows
        )
        for relation in ("SUPPORTS", "CONTRADICTS", "NEUTRAL", "UNCERTAIN")
    }
    full_text_count = sum(
        str(article.get("access_level") or "")
        in {"FULL_TEXT", "OPEN_ACCESS_FULL_TEXT"}
        and bool(article.get("assessments"))
        for article in articles
    )
    abstract_count = sum(
        str(article.get("access_level") or "") == "ABSTRACT_ONLY"
        and bool(article.get("assessments"))
        for article in articles
    )
    assessed_count = len({str(article.get("pmid") or id(article)) for article, _ in rows})
    direct_count = counts["SUPPORTS"] + counts["CONTRADICTS"]
    status, headline = _headline(counts)
    submitted = result.get("submitted_article") or {}
    claim = submitted.get("primary_claim") or (result.get("input") or {}).get("claim")
    submitted_scope = str(submitted.get("content_scope") or "UNKNOWN")

    if articles:
        located = (
            "Foi localizado 1 artigo"
            if len(articles) == 1
            else f"Foram localizados {len(articles)} artigos"
        )
        compared = (
            "1 teve trechos comparados"
            if assessed_count == 1
            else f"{assessed_count} tiveram trechos comparados"
        )
        summary = (
            f"{located}; {compared} com a alegação. A comparação encontrou "
            f"{_count_phrase(counts['SUPPORTS'], 'compatível', 'compatíveis')}, "
            f"{_count_phrase(counts['CONTRADICTS'], 'divergente', 'divergentes')}, "
            f"{_count_phrase(counts['NEUTRAL'], 'apenas contextual', 'apenas contextuais')} "
            f"e {_count_phrase(counts['UNCERTAIN'], 'inconclusivo', 'inconclusivos')}."
        )
    else:
        summary = (
            "Nenhum artigo independente pôde ser comparado nesta execução. "
            "Isso não indica que a alegação seja falsa."
        )

    relation_order = {"CONTRADICTS": 0, "SUPPORTS": 1, "NEUTRAL": 2, "UNCERTAIN": 3}
    findings = [
        _finding(article, assessment)
        for article, assessment in rows
        if (assessment.get("evidence") or {}).get("text")
    ]
    findings.sort(
        key=lambda item: (
            relation_order.get(str(item["relation"]), 4),
            -float(item["confidence"] or 0),
            str(item["article_title"]),
        )
    )

    caveats = [
        "O resultado mede compatibilidade com os trechos recuperados, não verdade médica."
    ]
    if submitted_scope in {"ABSTRACT", "ABSTRACT_ONLY"}:
        caveats.append("Do artigo enviado, foi possível ler somente o abstract.")
    if abstract_count:
        caveats.append(
            f"{abstract_count} {_plural(abstract_count, 'artigo independente', 'artigos independentes')} "
            "foram analisados somente pelo abstract."
        )
    if len(articles) > assessed_count:
        missing = len(articles) - assessed_count
        caveats.append(
            f"{missing} {_plural(missing, 'artigo recuperado', 'artigos recuperados')} "
            "não tiveram trecho comparável."
        )
    caveats = list(dict.fromkeys(caveats))[:4]

    if submitted_scope in {"ABSTRACT", "ABSTRACT_ONLY"}:
        next_action = (
            "Envie o PDF do artigo para analisar métodos, resultados, tabelas e páginas; "
            "depois confira manualmente os trechos independentes abaixo."
        )
    elif findings:
        next_action = (
            "Compare os trechos citados com o artigo original e observe diferenças de "
            "população, intervenção, método e desfecho."
        )
    else:
        next_action = (
            "Tente novamente mais tarde ou envie o PDF; nenhuma conclusão deve ser tomada "
            "sem evidência independente comparável."
        )

    submitted_reading = _SCOPE_LABELS.get(
        submitted_scope, submitted_scope.replace("_", " ").lower()
    )
    independent_reading = (
        "Foi recuperado 1 artigo independente"
        if len(articles) == 1
        else f"Foram recuperados {len(articles)} artigos independentes"
    )
    compared_verb = "foi comparado" if assessed_count == 1 else "foram comparados"
    submitted_prefix = (
        f"Artigo enviado: {submitted_reading}."
        if submitted
        else "Nenhum artigo específico foi enviado."
    )
    reading_summary = (
        f"{submitted_prefix} {independent_reading}; "
        f"{assessed_count} {compared_verb}: {full_text_count} com texto completo e "
        f"{abstract_count} somente pelo abstract."
    )

    return {
        "status": status,
        "headline": headline,
        "claim": claim,
        "summary": summary,
        "interpretation": _interpretation(status, direct_count, abstract_count),
        "reading": {
            "submitted_scope": submitted_scope,
            "submitted_scope_label": _SCOPE_LABELS.get(
                submitted_scope, submitted_scope.replace("_", " ").lower()
            ),
            "summary": reading_summary,
            "retrieved_count": len(articles),
            "assessed_count": assessed_count,
            "full_text_count": full_text_count,
            "abstract_only_count": abstract_count,
        },
        "evidence_balance": counts,
        "findings": findings,
        "caveats": caveats,
        "next_action": next_action,
    }
