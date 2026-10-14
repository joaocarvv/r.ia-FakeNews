"""Exporta a análise completa como Markdown com citações e dados de reprodução."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


RELATION_LABELS = {
    "SUPPORTS": "Compatível",
    "CONTRADICTS": "Incompatível",
    "NEUTRAL": "Neutro",
    "UNCERTAIN": "Incerto",
    "NOT_ASSESSED": "Não lido",
}
EDITORIAL_LABELS = {
    "RETRACTED": "RETRATADO",
    "EXPRESSION_OF_CONCERN": "Manifestação de preocupação",
    "PREPRINT": "Pré-publicação (sem revisão por pares)",
    "CORRECTED": "Com correção publicada",
}


def _text(value: Any) -> str:
    if value is None or value == "":
        return "Não informado"
    return " ".join(str(value).split())


def _cell(value: Any) -> str:
    return _text(value).replace("|", "\\|")


def _citations(items: Iterable[Mapping[str, Any]] | None) -> list[str]:
    lines = []
    for item in items or ():
        location = ", ".join(
            part
            for part in (
                _text(item.get("section")) if item.get("section") else "",
                f"p. {item['page']}" if item.get("page") else "",
            )
            if part
        )
        check = "verificada no texto" if item.get("verified") else "não verificada"
        lines.append(f"  > “{_text(item.get('quote'))}” — {location or 'local não identificado'} ({check})")
    return lines


def _dossier(report: Mapping[str, Any]) -> list[str]:
    overview = report.get("overview") or {}
    study = report.get("study") or {}
    coverage = report.get("coverage") or {}
    lines = [
        "## Dossiê do artigo",
        "",
        f"**Cobertura da leitura:** {_text(coverage.get('scope_label') or coverage.get('content_scope'))}",
        "",
        f"**Objetivo:** {_text(overview.get('purpose'))}",
        "",
        f"**Pergunta de pesquisa:** {_text(overview.get('research_question'))}",
        "",
        f"**Resumo:** {_text(overview.get('plain_language_summary'))}",
        "",
        f"**Conclusão dos autores:** {_text(overview.get('authors_conclusion'))}",
        "",
        "| Elemento | Descrição |",
        "| --- | --- |",
    ]
    for label, key in (
        ("Desenho declarado no texto", "design"),
        ("População", "population"),
        ("Amostra", "sample_size"),
        ("Intervenção/exposição", "intervention_or_exposure"),
        ("Comparador", "comparator"),
        ("Seguimento", "follow_up"),
    ):
        if study.get(key) and study[key] != "Não informado":
            lines.append(f"| {label} | {_cell(study[key])} |")
    if study.get("outcomes"):
        lines.append(f"| Desfechos | {_cell('; '.join(study['outcomes']))} |")
    if study.get("statistical_methods"):
        lines.append(f"| Métodos estatísticos | {_cell('; '.join(study['statistical_methods']))} |")
    lines.append("")
    for key, sources in (report.get("study_field_sources") or {}).items():
        for origin in sources:
            location = origin.get("section") or ""
            if origin.get("page"):
                location += f" p. {origin['page']}"
            lines.append(f"> {key}: “{_text(origin.get('quote'))}” — {location}")
    lines.append("")
    if report.get("main_findings"):
        lines += ["### Resultados principais", ""]
        for item in report["main_findings"]:
            lines.append(f"- **{_text(item.get('finding'))}** — {_text(item.get('numbers'))}")
            lines += _citations(item.get("citations"))
        lines.append("")
    if report.get("tables_figures"):
        lines += ["### Tabelas e figuras", ""]
        for item in report["tables_figures"]:
            lines.append(
                f"- **{_text(item.get('label'))}**: {_text(item.get('description'))} "
                f"Dados: {_text(item.get('key_data'))}"
            )
        lines.append("")
    if report.get("authors_declared_limitations"):
        lines += ["### Limitações declaradas pelos autores", ""]
        for item in report["authors_declared_limitations"]:
            lines.append(f"- {_text(item.get('limitation'))}")
            lines += _citations(item.get("citations"))
        lines.append("")
    if report.get("limitations"):
        lines += ["### Limitações identificadas na leitura crítica", ""]
        lines += [f"- {_text(item)}" for item in report["limitations"]]
        lines.append("")
    for title, key in (("Financiamento", "funding"), ("Conflitos de interesse", "conflicts_of_interest")):
        block = report.get(key)
        if block:
            lines += [f"### {title}", "", _text(block.get("statement")), ""]
            lines += _citations(block.get("citations"))
            lines.append("")
    return lines


def _claim(index: int, analysis: Mapping[str, Any]) -> list[str]:
    claim = analysis.get("claim") or {}
    profile = claim.get("profile") or {}
    result = analysis.get("result") or {}
    weighted = result.get("weighted_evidence") or {}
    verdict = weighted.get("verdict") or {}
    lines = [
        f"## Alegação {index}: {_text(claim.get('text'))}",
        "",
    ]
    notices = list(dict.fromkeys(
        passage["retrieval_notice"]
        for article in result.get("articles") or ()
        for passage in article.get("analyzed_passages") or ()
        if passage.get("retrieval_notice")
    ))
    if notices:
        lines += [f"> {_text(notice)}" for notice in notices] + [""]
    if claim.get("user_supplied"):
        lines += ["_Alegação adicionada pelo usuário; sem atribuição automática aos autores._", ""]
    if claim.get("quote"):
        location = ", ".join(
            part for part in (claim.get("section") or "", f"p. {claim['page']}" if claim.get("page") else "") if part
        )
        lines += [f"> “{_text(claim.get('quote'))}” — {location or 'local não identificado'}", ""]
    if profile:
        lines += [
            f"**Tipo:** {_text(profile.get('claim_type_label'))} · **Importância:** {_text(profile.get('importance'))}",
            "",
            f"**PICO:** P: {_text(profile.get('population'))}; I/E: {_text(profile.get('intervention'))}; "
            f"C: {_text(profile.get('comparator'))}; O: {_text(profile.get('outcome'))}",
            "",
        ]
    if verdict:
        synthesis_label = (
            f"**Síntese ponderada:** {_text(verdict.get('label'))} — "
            f"certeza {_text(verdict.get('certainty_label'))}"
            if verdict.get("certainty_label")
            else f"**Balanço descritivo:** {_text(verdict.get('label'))}"
        )
        lines += [
            synthesis_label,
            "",
            _text(verdict.get("explanation")),
            "",
            *[f"- {_text(item)}" for item in verdict.get("certainty_reasons") or ()],
            "",
            f"_{_text((weighted.get('absence') or {}).get('message'))}_",
            "",
        ]
    rows = weighted.get("rows") or []
    if rows:
        methodology_assessed = bool(verdict.get("certainty_label"))
        lines += (
            [
                "| Ano | Estudo | Desenho | População (n) | Efeito | Relação | Comparabilidade | Risco de viés | Peso |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
            if methodology_assessed
            else [
                "| Ano | Estudo | Tipo informado / declaração | População (n) | Efeito | Relação textual |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in rows:
            title = row.get("title_pt") or row.get("title")
            status = EDITORIAL_LABELS.get(row.get("editorial_status") or "")
            if status:
                title = f"{title} [{status}]"
            link = row.get("url") or (f"https://doi.org/{row['doi']}" if row.get("doi") else None)
            study = f"[{_cell(title)}]({link})" if link else _cell(title)
            cells = [
                _cell(row.get("year")),
                study,
                _cell(row.get("design_label")) if methodology_assessed else _cell(
                    "; ".join(row.get("publication_types") or ()) +
                    (" · PubMed, PublicationType" if row.get("publication_types_source") else "") +
                    (f" · declaração no texto: {row['design_detail']}" if row.get("design_detail") else "")
                ),
                _cell("; ".join(filter(None, [row.get("population"), row.get("sample_size")]))),
                _cell(row.get("effect_estimate")),
                _cell(RELATION_LABELS.get(row.get("relation"), row.get("relation"))),
            ]
            if methodology_assessed:
                cells.extend(
                    (
                        _cell(row.get("comparability_label")),
                        _cell(
                            f"{row.get('rob_label')} ({row.get('rob_tool_label')})"
                            if row.get("rob_label")
                            else None
                        ),
                        _cell(row.get("weight")),
                    )
                )
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
        lines += ["### Citações dos estudos", ""]
        for row in rows:
            for field, source in (row.get("field_sources") or {}).items():
                lines.append(f"- **{_text(row.get('title'))} — {_text(field)}:** “{_text(source.get('text'))}” ({_text(source.get('section'))})")
            if not row.get("quote"):
                continue
            location = ", ".join(
                part
                for part in (row.get("quote_section") or "", f"p. {row['quote_page']}" if row.get("quote_page") else "")
                if part
            )
            lines.append(f"- **{_text(row.get('title_pt') or row.get('title'))}**")
            lines.append(f"  > “{_text(row.get('quote'))}” — {location or 'trecho'}")
            if row.get("quote_pt"):
                lines.append(f"  > Tradução: “{_text(row.get('quote_pt'))}”")
        lines.append("")
    reproducibility = result.get("reproducibility") or {}
    if reproducibility:
        lines += [
            "### Reprodução",
            "",
            f"- Executado em: {_text(reproducibility.get('executed_at'))}",
            f"- Profundidade: {_text(reproducibility.get('depth'))}",
            f"- Modelo de evidência: {_text(reproducibility.get('evidence_model'))}",
            f"- Modelo de tradução: {_text(reproducibility.get('translation_model'))}",
            f"- Parâmetros: {_text(reproducibility.get('parameters'))}",
            "- Consultas:",
            *[f"  - `{query}`" for query in reproducibility.get("queries") or ()],
            "",
        ]
    return lines


def render_markdown_report(job: Mapping[str, Any]) -> str:
    result = job.get("result") or {}
    submitted = result.get("submitted_article") or {}
    lines = [
        f"# Relatório artfact — {_text(submitted.get('title') or job.get('article_reference'))}",
        "",
        f"- Análise: `{job.get('analysis_id')}`",
        f"- Fonte: {_text((result.get('input') or {}).get('source') or job.get('article_reference'))}",
        *([f"- DOI: {_text(submitted['doi'])}"] if submitted.get("doi") else []),
        f"- Gerado em: {_text(job.get('updated_at'))}",
        "",
        "> Este relatório mede compatibilidade entre alegações e literatura recuperada. "
        "Não é diagnóstico, não substitui revisão sistemática e pode conter erros do modelo.",
        "",
    ]
    structured = (result.get("article_dossier") or {}).get("structured_fields") or {}
    if structured:
        lines += ["## Metadados informados pela API", ""]
        for field, origin in structured.items():
            value = origin.get("value")
            rendered = "; ".join(map(str, value)) if isinstance(value, list) else _text(value)
            lines.append(f"- {field}: {rendered} — {origin.get('source')}, campo {origin.get('field')}")
        lines.append("")
    if result.get("whole_article_analysis"):
        lines += _dossier(result["whole_article_analysis"])
    for index, analysis in enumerate(result.get("claim_analyses") or (), start=1):
        lines += _claim(index, analysis)
    reproducibility = result.get("reproducibility") or {}
    if reproducibility:
        lines += [
            "## Reprodução da leitura do artigo",
            "",
            *[f"- {key}: {_text(value)}" for key, value in reproducibility.items()],
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"
