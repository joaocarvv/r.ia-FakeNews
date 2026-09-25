"""Agrega relações por artigo sem tratar trechos correlacionados como estudos."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .evidence_classification import EvidenceAssessment, RelationLabel
from .retrieval import RetrievalError


class QualityLevel(str, Enum):
    """Qualidade metodológica atribuída por uma avaliação externa e auditável."""

    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    UNCLEAR = "UNCLEAR"


class EvidenceDirection(str, Enum):
    """Direção do sinal agregado, separada da força da evidência."""

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


class EvidenceStrength(str, Enum):
    """Força preliminar do conjunto analisado."""

    INSUFFICIENT = "INSUFFICIENT"
    LOW = "LOW"
    MODERATE = "MODERATE"


_QUALITY_WEIGHTS = {
    QualityLevel.HIGH: 1.0,
    QualityLevel.MODERATE: 0.75,
    QualityLevel.LOW: 0.50,
    QualityLevel.UNCLEAR: 0.25,
}

_DIRECTION_NAMES = {
    EvidenceDirection.SUPPORTS: "de apoio",
    EvidenceDirection.CONTRADICTS: "de contradição",
    EvidenceDirection.NEUTRAL: "neutro",
    EvidenceDirection.MIXED: "misto",
}


@dataclass(frozen=True)
class ArticleQualityProfile:
    """Qualidade fornecida com justificativa; não é inferida pelo agregador."""

    pmid: str
    level: QualityLevel
    study_design: str
    rationale: str
    source_url: str

    def __post_init__(self) -> None:
        if not self.pmid.strip():
            raise RetrievalError("O PMID do perfil de qualidade não pode estar vazio.")
        if not self.study_design.strip():
            raise RetrievalError("O desenho do estudo não pode estar vazio.")
        if not self.rationale.strip():
            raise RetrievalError("A qualidade precisa de uma justificativa.")
        if not self.source_url.strip():
            raise RetrievalError("O perfil de qualidade precisa de uma fonte.")

    @property
    def weight(self) -> float:
        return _QUALITY_WEIGHTS[self.level]


@dataclass(frozen=True)
class ArticleSynthesis:
    """Resumo de um artigo; cada trecho influencia apenas este nível."""

    pmid: str
    direction: EvidenceDirection
    support_probability: float
    contradiction_probability: float
    neutral_probability: float
    assessment_count: int
    relation_counts: tuple[tuple[str, int], ...]
    has_internal_conflict: bool
    uncertain_count: int
    quality: ArticleQualityProfile


@dataclass(frozen=True)
class CorpusSynthesis:
    """Síntese entre artigos, mantendo direção, força e conflitos separados."""

    direction: EvidenceDirection
    strength: EvidenceStrength
    support_probability: float
    contradiction_probability: float
    neutral_probability: float
    article_count: int
    has_conflict: bool
    rationale: str
    articles: tuple[ArticleSynthesis, ...]


@dataclass(frozen=True)
class SynthesisConfig:
    """Limites transparentes do agregador preliminar do MVP."""

    minimum_direction_margin: float = 0.10
    minimum_articles: int = 2

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_direction_margin <= 1:
            raise RetrievalError("minimum_direction_margin deve estar entre 0 e 1.")
        if self.minimum_articles < 2:
            raise RetrievalError("minimum_articles deve ser ao menos 2.")


def _direction_from_probabilities(
    support: float,
    contradiction: float,
    neutral: float,
    *,
    minimum_margin: float,
    conflict: bool,
) -> EvidenceDirection:
    if conflict:
        return EvidenceDirection.MIXED
    ranked = sorted(
        ((support, "support"), (contradiction, "contradiction"), (neutral, "neutral")),
        key=lambda item: (-item[0], item[1]),
    )
    if ranked[0][0] - ranked[1][0] < minimum_margin:
        return EvidenceDirection.MIXED
    return {
        "support": EvidenceDirection.SUPPORTS,
        "contradiction": EvidenceDirection.CONTRADICTS,
        "neutral": EvidenceDirection.NEUTRAL,
    }[ranked[0][1]]


def _article_synthesis(
    pmid: str,
    assessments: Sequence[EvidenceAssessment],
    quality: ArticleQualityProfile,
    config: SynthesisConfig,
) -> ArticleSynthesis:
    count = len(assessments)
    support = sum(item.probabilities.support for item in assessments) / count
    contradiction = sum(item.probabilities.contradiction for item in assessments) / count
    neutral = sum(item.probabilities.neutral for item in assessments) / count
    relation_counts = Counter(item.relation.value for item in assessments)
    has_internal_conflict = (
        relation_counts[RelationLabel.SUPPORTS.value] > 0
        and relation_counts[RelationLabel.CONTRADICTS.value] > 0
    )
    direction = _direction_from_probabilities(
        support,
        contradiction,
        neutral,
        minimum_margin=config.minimum_direction_margin,
        conflict=has_internal_conflict,
    )
    return ArticleSynthesis(
        pmid=pmid,
        direction=direction,
        support_probability=support,
        contradiction_probability=contradiction,
        neutral_probability=neutral,
        assessment_count=count,
        relation_counts=tuple(sorted(relation_counts.items())),
        has_internal_conflict=has_internal_conflict,
        uncertain_count=relation_counts[RelationLabel.UNCERTAIN.value],
        quality=quality,
    )


def _strength(
    articles: Sequence[ArticleSynthesis],
    *,
    has_conflict: bool,
    minimum_articles: int,
) -> EvidenceStrength:
    if len(articles) < minimum_articles:
        return EvidenceStrength.INSUFFICIENT
    if has_conflict:
        return EvidenceStrength.LOW
    if any(article.quality.level is QualityLevel.UNCLEAR for article in articles):
        return EvidenceStrength.LOW
    if all(
        article.quality.level in {QualityLevel.HIGH, QualityLevel.MODERATE}
        for article in articles
    ):
        return EvidenceStrength.MODERATE
    return EvidenceStrength.LOW


def synthesize_evidence(
    assessments: Sequence[EvidenceAssessment],
    quality_profiles: Sequence[ArticleQualityProfile],
    config: SynthesisConfig | None = None,
) -> CorpusSynthesis:
    """Resume trechos por artigo e então combina artigos ponderados por qualidade."""

    if not assessments:
        raise RetrievalError("Ao menos uma avaliação é necessária para a síntese.")
    active_config = config or SynthesisConfig()
    grouped: dict[str, list[EvidenceAssessment]] = defaultdict(list)
    for assessment in assessments:
        if not assessment.evidence.pmid.strip():
            raise RetrievalError("Toda avaliação precisa de um PMID para agregação.")
        grouped[assessment.evidence.pmid].append(assessment)

    profiles = {profile.pmid: profile for profile in quality_profiles}
    if len(profiles) != len(quality_profiles):
        raise RetrievalError("Há perfis de qualidade duplicados para o mesmo PMID.")
    if set(profiles) != set(grouped):
        raise RetrievalError(
            "Deve existir exatamente um perfil de qualidade para cada artigo avaliado."
        )

    articles = tuple(
        _article_synthesis(pmid, grouped[pmid], profiles[pmid], active_config)
        for pmid in sorted(grouped)
    )
    directions = {article.direction for article in articles}
    directional = directions & {
        EvidenceDirection.SUPPORTS,
        EvidenceDirection.CONTRADICTS,
    }
    has_conflict = (
        any(article.has_internal_conflict for article in articles)
        or len(directional) > 1
        or EvidenceDirection.MIXED in directions
    )

    total_weight = sum(article.quality.weight for article in articles)
    support = sum(
        article.support_probability * article.quality.weight for article in articles
    ) / total_weight
    contradiction = sum(
        article.contradiction_probability * article.quality.weight
        for article in articles
    ) / total_weight
    neutral = sum(
        article.neutral_probability * article.quality.weight for article in articles
    ) / total_weight
    direction = _direction_from_probabilities(
        support,
        contradiction,
        neutral,
        minimum_margin=active_config.minimum_direction_margin,
        conflict=has_conflict,
    )
    strength = _strength(
        articles,
        has_conflict=has_conflict,
        minimum_articles=active_config.minimum_articles,
    )

    if strength is EvidenceStrength.INSUFFICIENT:
        article_label = "artigo independente" if len(articles) == 1 else "artigos independentes"
        rationale = (
            f"Há um sinal {_DIRECTION_NAMES[direction]}, mas apenas {len(articles)} "
            f"{article_label}; "
            f"são necessários ao menos {active_config.minimum_articles}."
        )
    elif has_conflict:
        rationale = "Foram encontrados sinais conflitantes; o conflito foi preservado."
    elif strength is EvidenceStrength.MODERATE:
        rationale = (
            "Artigos independentes apontam na mesma direção e possuem qualidade "
            "moderada ou alta, sem conflito detectado."
        )
    else:
        rationale = (
            "A direção é consistente, mas ao menos um perfil possui qualidade baixa "
            "ou ainda não esclarecida."
        )

    return CorpusSynthesis(
        direction=direction,
        strength=strength,
        support_probability=support,
        contradiction_probability=contradiction,
        neutral_probability=neutral,
        article_count=len(articles),
        has_conflict=has_conflict,
        rationale=rationale,
        articles=articles,
    )
