"""Gera uma resposta explicável a partir de resultados científicos estruturados."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .amstar2 import AmstarAssessment
from .evidence_synthesis import (
    CorpusSynthesis,
    EvidenceDirection,
    EvidenceStrength,
    QualityLevel,
)
from .retrieval import RetrievalError


class ReportConclusion(str, Enum):
    """Conclusão comunicável, sem reduzir a análise a um veredito binário."""

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    COMPATIBLE_WITH_EVIDENCE = "COMPATIBLE_WITH_EVIDENCE"
    INCOMPATIBLE_WITH_EVIDENCE = "INCOMPATIBLE_WITH_EVIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class ReportSource:
    label: str
    url: str
    pmid: str | None = None

    def __post_init__(self) -> None:
        if not self.label.strip() or not self.url.strip():
            raise RetrievalError("Toda fonte precisa de rótulo e URL.")
        if not self.url.startswith(("https://", "http://")):
            raise RetrievalError("A URL da fonte deve usar HTTP ou HTTPS.")


@dataclass(frozen=True)
class MethodologySummary:
    pmid: str
    instrument: str
    confidence: str
    quality_level: QualityLevel
    critical_flaws: tuple[int, ...]
    single_reviewer: bool
    rationale: str
    applicability_note: str
    source_url: str

    def __post_init__(self) -> None:
        if not self.pmid.strip() or not self.instrument.strip():
            raise RetrievalError("A avaliação metodológica precisa de PMID e instrumento.")
        if not self.confidence.strip() or not self.rationale.strip():
            raise RetrievalError("Confiança e justificativa metodológica são obrigatórias.")
        if not self.source_url.startswith(("https://", "http://")):
            raise RetrievalError("A avaliação metodológica precisa de uma URL válida.")


@dataclass(frozen=True)
class EvidenceReport:
    claim: str
    conclusion: ReportConclusion
    headline: str
    summary: str
    synthesis: CorpusSynthesis
    methodology: tuple[MethodologySummary, ...]
    limitations: tuple[str, ...]
    sources: tuple[ReportSource, ...]


_CONCLUSION_HEADLINES = {
    ReportConclusion.INSUFFICIENT_EVIDENCE: "Evidência insuficiente",
    ReportConclusion.COMPATIBLE_WITH_EVIDENCE: "Alegação compatível com as evidências analisadas",
    ReportConclusion.INCOMPATIBLE_WITH_EVIDENCE: "Alegação incompatível com as evidências analisadas",
    ReportConclusion.CONFLICTING_EVIDENCE: "Evidências conflitantes",
    ReportConclusion.INCONCLUSIVE: "Resultado inconclusivo",
}

_DIRECTION_LABELS = {
    EvidenceDirection.SUPPORTS: "apoio à alegação",
    EvidenceDirection.CONTRADICTS: "contradição da alegação",
    EvidenceDirection.NEUTRAL: "resultado neutro",
    EvidenceDirection.MIXED: "sinais mistos",
}

_STRENGTH_LABELS = {
    EvidenceStrength.INSUFFICIENT: "insuficiente",
    EvidenceStrength.LOW: "baixa",
    EvidenceStrength.MODERATE: "moderada",
}

_CONFIDENCE_LABELS = {
    "HIGH": "alta",
    "MODERATE": "moderada",
    "LOW": "baixa",
    "CRITICALLY_LOW": "criticamente baixa",
}

_QUALITY_LABELS = {
    QualityLevel.HIGH: "alta",
    QualityLevel.MODERATE: "moderada",
    QualityLevel.LOW: "baixa",
    QualityLevel.UNCLEAR: "não esclarecida",
}


def methodology_summary_from_amstar(
    pmid: str,
    assessment: AmstarAssessment,
    quality_level: QualityLevel,
) -> MethodologySummary:
    """Converte a avaliação AMSTAR 2 em uma estrutura própria para comunicação."""

    return MethodologySummary(
        pmid=pmid,
        instrument="AMSTAR 2",
        confidence=assessment.confidence.value,
        quality_level=quality_level,
        critical_flaws=assessment.critical_flaws,
        single_reviewer=assessment.single_reviewer,
        rationale=assessment.rationale,
        applicability_note=assessment.applicability_note,
        source_url=assessment.instrument_url,
    )


def _conclusion_for(synthesis: CorpusSynthesis) -> ReportConclusion:
    if synthesis.strength is EvidenceStrength.INSUFFICIENT:
        return ReportConclusion.INSUFFICIENT_EVIDENCE
    if synthesis.has_conflict or synthesis.direction is EvidenceDirection.MIXED:
        return ReportConclusion.CONFLICTING_EVIDENCE
    if synthesis.direction is EvidenceDirection.SUPPORTS:
        return ReportConclusion.COMPATIBLE_WITH_EVIDENCE
    if synthesis.direction is EvidenceDirection.CONTRADICTS:
        return ReportConclusion.INCOMPATIBLE_WITH_EVIDENCE
    return ReportConclusion.INCONCLUSIVE


def _summary_for(synthesis: CorpusSynthesis, conclusion: ReportConclusion) -> str:
    direction = _DIRECTION_LABELS[synthesis.direction]
    if conclusion is ReportConclusion.INSUFFICIENT_EVIDENCE:
        article_label = (
            "artigo independente"
            if synthesis.article_count == 1
            else "artigos independentes"
        )
        verb = "fornece" if synthesis.article_count == 1 else "fornecem"
        return (
            f"A análise encontrou um sinal de {direction}, mas {synthesis.article_count} "
            f"{article_label} não {verb} evidência suficiente para uma "
            "conclusão segura."
        )
    if conclusion is ReportConclusion.CONFLICTING_EVIDENCE:
        return "Os artigos ou trechos analisados apontam em direções diferentes."
    if conclusion is ReportConclusion.COMPATIBLE_WITH_EVIDENCE:
        return "O conjunto analisado apresenta evidências compatíveis com a alegação."
    if conclusion is ReportConclusion.INCOMPATIBLE_WITH_EVIDENCE:
        return "O conjunto analisado apresenta evidências incompatíveis com a alegação."
    return "O conjunto analisado não apresenta direção suficientemente clara."


def generate_evidence_report(
    claim: str,
    synthesis: CorpusSynthesis,
    methodology: Sequence[MethodologySummary],
    sources: Sequence[ReportSource],
    additional_limitations: Sequence[str] = (),
) -> EvidenceReport:
    """Monta o relatório com regras determinísticas e fontes auditáveis."""

    if not claim.strip():
        raise RetrievalError("A alegação do relatório não pode estar vazia.")
    if not sources:
        raise RetrievalError("O relatório precisa apresentar ao menos uma fonte.")

    source_urls = [source.url for source in sources]
    if len(set(source_urls)) != len(source_urls):
        raise RetrievalError("O relatório contém fontes duplicadas.")

    article_pmids = {article.pmid for article in synthesis.articles}
    source_pmids = {source.pmid for source in sources if source.pmid}
    if not article_pmids.issubset(source_pmids):
        raise RetrievalError("Cada artigo sintetizado precisa de uma fonte com o mesmo PMID.")

    methodology_pmids = [item.pmid for item in methodology]
    if len(set(methodology_pmids)) != len(methodology_pmids):
        raise RetrievalError("Há avaliações metodológicas duplicadas para o mesmo PMID.")
    if not set(methodology_pmids).issubset(article_pmids):
        raise RetrievalError("A avaliação metodológica pertence a um artigo não sintetizado.")

    limitations: list[str] = []
    if synthesis.strength is EvidenceStrength.INSUFFICIENT:
        article_label = (
            "artigo independente"
            if synthesis.article_count == 1
            else "artigos independentes"
        )
        verb = "Foi analisado" if synthesis.article_count == 1 else "Foram analisados"
        limitations.append(f"{verb} apenas {synthesis.article_count} {article_label}.")
    if synthesis.has_conflict:
        limitations.append("Há sinais conflitantes no conjunto analisado.")
    for item in methodology:
        if item.critical_flaws:
            flaw_count = len(item.critical_flaws)
            domain_label = (
                "domínio crítico incompleto"
                if flaw_count == 1
                else "domínios críticos incompletos"
            )
            limitations.append(
                f"O artigo PMID {item.pmid} possui {flaw_count} {domain_label} no "
                f"{item.instrument}: {item.critical_flaws}."
            )
        if item.single_reviewer:
            limitations.append(
                f"A avaliação metodológica do PMID {item.pmid} foi preliminar e feita "
                "por um único revisor."
            )
        if item.applicability_note:
            limitations.append(item.applicability_note)
    limitations.extend(text.strip() for text in additional_limitations if text.strip())
    limitations = list(dict.fromkeys(limitations))

    conclusion = _conclusion_for(synthesis)
    return EvidenceReport(
        claim=claim.strip(),
        conclusion=conclusion,
        headline=_CONCLUSION_HEADLINES[conclusion],
        summary=_summary_for(synthesis, conclusion),
        synthesis=synthesis,
        methodology=tuple(methodology),
        limitations=tuple(limitations),
        sources=tuple(sources),
    )


def render_evidence_report_markdown(report: EvidenceReport) -> str:
    """Renderiza a resposta em Markdown sem delegar a conclusão a um modelo generativo."""

    synthesis = report.synthesis
    lines = [
        f"## Conclusão: {report.headline}",
        "",
        report.summary,
        "",
        "### O que as evidências sugerem",
        "",
        f"- Direção do sinal: **{_DIRECTION_LABELS[synthesis.direction]}**.",
        (
            "- Probabilidades médias do classificador textual — não representam a "
            f"probabilidade de a alegação estar correta: apoio {synthesis.support_probability:.1%}, "
            f"contradição {synthesis.contradiction_probability:.1%} e "
            f"neutro {synthesis.neutral_probability:.1%}."
        ),
        f"- Artigos independentes analisados: **{synthesis.article_count}**.",
        "",
        "### Confiança da análise",
        "",
        f"- Força do conjunto: **{_STRENGTH_LABELS[synthesis.strength]}**.",
    ]
    if report.methodology:
        for item in report.methodology:
            confidence = _CONFIDENCE_LABELS.get(
                item.confidence, item.confidence.replace("_", " ").lower()
            )
            lines.append(
                f"- PMID {item.pmid}: confiança metodológica **{confidence}** "
                f"pelo {item.instrument}; qualidade usada na síntese: "
                f"**{_QUALITY_LABELS[item.quality_level]}**."
            )
    else:
        lines.append("- Não foi fornecida uma avaliação metodológica estruturada.")

    lines.extend(["", "### Por que a confiança é limitada", ""])
    if report.limitations:
        lines.extend(f"- {limitation}" for limitation in report.limitations)
    else:
        lines.append("- Nenhuma limitação adicional foi registrada.")

    lines.extend(["", "### Fontes", ""])
    lines.extend(f"- [{source.label}]({source.url})" for source in report.sources)
    return "\n".join(lines)
