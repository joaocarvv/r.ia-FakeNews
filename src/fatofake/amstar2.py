"""Estrutura uma avaliação AMSTAR 2 rastreável, sem produzir escore numérico."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .evidence_synthesis import ArticleQualityProfile, QualityLevel
from .pubmed import Publication
from .quality_validation import ArticleQualityReport, StudyDesign
from .retrieval import RetrievalError


AMSTAR2_SOURCE_URL = "https://www.bmj.com/content/358/bmj.j4008"


class AmstarRating(str, Enum):
    YES = "YES"
    PARTIAL_YES = "PARTIAL_YES"
    NO = "NO"


class AmstarConfidence(str, Enum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    CRITICALLY_LOW = "CRITICALLY_LOW"


@dataclass(frozen=True)
class AmstarItem:
    item_id: int
    domain: str
    critical: bool = False


AMSTAR2_ITEMS = (
    AmstarItem(1, "Pergunta e critérios estruturados por PICO"),
    AmstarItem(2, "Protocolo definido antes da revisão", True),
    AmstarItem(3, "Justificativa para os desenhos incluídos"),
    AmstarItem(4, "Busca bibliográfica abrangente", True),
    AmstarItem(5, "Seleção dos estudos em duplicata"),
    AmstarItem(6, "Extração dos dados em duplicata"),
    AmstarItem(7, "Lista e justificativa dos estudos excluídos", True),
    AmstarItem(8, "Descrição detalhada dos estudos incluídos"),
    AmstarItem(9, "Avaliação adequada do risco de viés", True),
    AmstarItem(10, "Financiamento dos estudos primários"),
    AmstarItem(11, "Métodos apropriados para a meta-análise", True),
    AmstarItem(12, "Impacto do risco de viés sobre a síntese"),
    AmstarItem(13, "Risco de viés considerado na interpretação", True),
    AmstarItem(14, "Heterogeneidade explicada e discutida"),
    AmstarItem(15, "Viés de publicação investigado e discutido", True),
    AmstarItem(16, "Conflitos e financiamento da revisão declarados"),
)
_ITEMS_BY_ID = {item.item_id: item for item in AMSTAR2_ITEMS}


@dataclass(frozen=True)
class AmstarJudgment:
    item_id: int
    rating: AmstarRating
    evidence: str
    section: str
    source_url: str
    reviewer_note: str = ""

    def __post_init__(self) -> None:
        if self.item_id not in _ITEMS_BY_ID:
            raise RetrievalError(f"Item AMSTAR 2 inválido: {self.item_id}.")
        if not self.evidence.strip():
            raise RetrievalError("Todo julgamento AMSTAR 2 precisa de evidência.")
        if not self.section.strip() or not self.source_url.strip():
            raise RetrievalError("Seção e fonte são obrigatórias em cada julgamento.")


@dataclass(frozen=True)
class AmstarAssessment:
    confidence: AmstarConfidence
    critical_flaws: tuple[int, ...]
    noncritical_weaknesses: tuple[int, ...]
    judgments: tuple[AmstarJudgment, ...]
    reviewer: str
    single_reviewer: bool
    rationale: str
    applicability_note: str
    instrument_url: str = AMSTAR2_SOURCE_URL


def assess_amstar2(
    judgments: Sequence[AmstarJudgment],
    *,
    reviewer: str,
    single_reviewer: bool = True,
    applicability_note: str = "",
) -> AmstarAssessment:
    """Aplica as regras por falhas críticas; nunca soma os itens em um escore."""

    if not reviewer.strip():
        raise RetrievalError("O avaliador AMSTAR 2 precisa ser identificado.")
    by_id = {judgment.item_id: judgment for judgment in judgments}
    if len(by_id) != len(judgments):
        raise RetrievalError("Há julgamentos duplicados para um item AMSTAR 2.")
    if set(by_id) != set(_ITEMS_BY_ID):
        missing = sorted(set(_ITEMS_BY_ID) - set(by_id))
        raise RetrievalError(f"Todos os 16 itens são obrigatórios; ausentes: {missing}.")

    ordered = tuple(by_id[item_id] for item_id in sorted(by_id))
    critical_flaws = tuple(
        judgment.item_id
        for judgment in ordered
        if _ITEMS_BY_ID[judgment.item_id].critical
        and judgment.rating is not AmstarRating.YES
    )
    noncritical_weaknesses = tuple(
        judgment.item_id
        for judgment in ordered
        if judgment.rating is not AmstarRating.YES
        and not _ITEMS_BY_ID[judgment.item_id].critical
    )
    if len(critical_flaws) > 1:
        confidence = AmstarConfidence.CRITICALLY_LOW
    elif len(critical_flaws) == 1:
        confidence = AmstarConfidence.LOW
    elif len(noncritical_weaknesses) > 1:
        confidence = AmstarConfidence.MODERATE
    else:
        confidence = AmstarConfidence.HIGH

    rationale = (
        f"Foram identificadas {len(critical_flaws)} falha(s) crítica(s) "
        f"nos itens {critical_flaws or 'nenhum'} e "
        f"{len(noncritical_weaknesses)} fraqueza(s) adicional(is). "
        "O resultado deriva dos domínios, não de uma soma de pontos."
    )
    if single_reviewer:
        rationale += " Avaliação preliminar realizada por um único revisor."
    if applicability_note.strip():
        rationale += f" Limitação de aplicabilidade: {applicability_note.strip()}"
    return AmstarAssessment(
        confidence=confidence,
        critical_flaws=critical_flaws,
        noncritical_weaknesses=noncritical_weaknesses,
        judgments=ordered,
        reviewer=reviewer.strip(),
        single_reviewer=single_reviewer,
        rationale=rationale,
        applicability_note=applicability_note.strip(),
    )


def quality_profile_from_amstar(
    publication: Publication,
    quality_report: ArticleQualityReport,
    assessment: AmstarAssessment,
) -> ArticleQualityProfile:
    """Converte confiança AMSTAR 2 para o perfil usado na síntese."""

    if quality_report.pmid != publication.pmid:
        raise RetrievalError("O relatório de qualidade pertence a outro artigo.")
    if quality_report.study_design is not StudyDesign.SYSTEMATIC_REVIEW_META_ANALYSIS:
        raise RetrievalError("AMSTAR 2 exige uma revisão sistemática elegível.")
    level = {
        AmstarConfidence.HIGH: QualityLevel.HIGH,
        AmstarConfidence.MODERATE: QualityLevel.MODERATE,
        AmstarConfidence.LOW: QualityLevel.LOW,
        AmstarConfidence.CRITICALLY_LOW: QualityLevel.LOW,
    }[assessment.confidence]
    return ArticleQualityProfile(
        pmid=publication.pmid,
        level=level,
        study_design=quality_report.study_design.value,
        rationale=(
            f"AMSTAR 2: confiança {assessment.confidence.value}. "
            f"{assessment.rationale}"
        ),
        source_url=publication.url,
    )
