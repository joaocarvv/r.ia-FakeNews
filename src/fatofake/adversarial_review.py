"""Revisão adversarial com proveniência verificável e abstenção conservadora."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Sequence

from .evidence_classification import EvidenceAssessment, RelationLabel
from .report_generation import EvidenceReport, ReportConclusion
from .retrieval import RetrievalError


AUTOMATED_REVIEW_DISCLAIMER = (
    "Esta é uma análise automatizada e experimental da literatura recuperada. "
    "Ela pode omitir estudos ou interpretar evidências incorretamente, não determina "
    "se uma alegação é verdadeira e não substitui avaliação profissional ou revisão "
    "sistemática. Consulte os trechos, fontes e limitações apresentados antes de "
    "formar uma conclusão."
)


class ReviewStatus(str, Enum):
    """Resultado da revisão, sem equivaler a verdade clínica."""

    CORROBORATED = "CORROBORATED"
    DISPUTED = "DISPUTED"
    INSUFFICIENT = "INSUFFICIENT"


class IssueSeverity(str, Enum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class CitedObservation:
    """Interpretação produzida pelo pesquisador ligada a um trecho existente."""

    observation_id: str
    statement_id: str
    pmid: str
    quote: str
    relation: RelationLabel
    source_url: str
    interpretation: str


@dataclass(frozen=True)
class ResearchDraft:
    """Saída estruturada do agente pesquisador."""

    summary: str
    observations: tuple[CitedObservation, ...]
    search_queries: tuple[str, ...]
    limitations: tuple[str, ...]
    model_name: str
    prompt_version: str


@dataclass(frozen=True)
class CritiqueIssue:
    code: str
    severity: IssueSeverity
    message: str
    observation_id: str | None = None


@dataclass(frozen=True)
class AdversarialCritique:
    """Saída estruturada do agente crítico independente."""

    summary: str
    issues: tuple[CritiqueIssue, ...]
    model_name: str
    prompt_version: str


@dataclass(frozen=True)
class ProvenanceProblem:
    code: str
    message: str
    observation_id: str | None = None


@dataclass(frozen=True)
class AdversarialReviewResult:
    """Decisão do árbitro e todos os artefatos necessários para auditoria."""

    status: ReviewStatus
    rationale: str
    draft: ResearchDraft
    critique: AdversarialCritique
    provenance_problems: tuple[ProvenanceProblem, ...]
    cited_article_count: int
    disclaimer: str = AUTOMATED_REVIEW_DISCLAIMER


class EvidenceResearcher(Protocol):
    def research(
        self,
        claim: str,
        assessments: Sequence[EvidenceAssessment],
        report: EvidenceReport,
    ) -> ResearchDraft:
        """Produz interpretação estruturada, limitada às evidências fornecidas."""


class EvidenceCritic(Protocol):
    def critique(
        self,
        claim: str,
        assessments: Sequence[EvidenceAssessment],
        report: EvidenceReport,
        draft: ResearchDraft,
    ) -> AdversarialCritique:
        """Procura erros, extrapolações, conflitos e limitações ignoradas."""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


class AdversarialReviewService:
    """Coordena dois agentes, mas reserva a decisão a regras verificáveis."""

    def __init__(
        self,
        researcher: EvidenceResearcher,
        critic: EvidenceCritic,
        *,
        minimum_cited_articles: int = 2,
    ) -> None:
        if minimum_cited_articles < 2:
            raise RetrievalError("minimum_cited_articles deve ser ao menos 2.")
        self._researcher = researcher
        self._critic = critic
        self._minimum_cited_articles = minimum_cited_articles

    @staticmethod
    def _validate_context(
        claim: str,
        assessments: Sequence[EvidenceAssessment],
        report: EvidenceReport,
    ) -> None:
        if not claim.strip():
            raise RetrievalError("A alegação da revisão não pode estar vazia.")
        if not assessments:
            raise RetrievalError("A revisão precisa de avaliações de evidência.")
        expected_claim = _normalize(claim)
        if _normalize(report.claim) != expected_claim or any(
            _normalize(item.claim) != expected_claim for item in assessments
        ):
            raise RetrievalError("Alegação, avaliações e relatório não correspondem.")

    @staticmethod
    def _provenance_problems(
        draft: ResearchDraft,
        assessments: Sequence[EvidenceAssessment],
    ) -> tuple[ProvenanceProblem, ...]:
        catalog = {item.evidence.statement_id: item for item in assessments}
        problems: list[ProvenanceProblem] = []
        seen_observations: set[str] = set()

        if not draft.model_name.strip() or not draft.prompt_version.strip():
            problems.append(
                ProvenanceProblem(
                    code="MISSING_RESEARCH_METADATA",
                    message="O pesquisador não informou modelo e versão do prompt.",
                )
            )
        if not draft.observations:
            problems.append(
                ProvenanceProblem(
                    code="NO_CITED_OBSERVATIONS",
                    message="O pesquisador não apresentou observações citadas.",
                )
            )

        for observation in draft.observations:
            if not observation.observation_id.strip():
                problems.append(
                    ProvenanceProblem(
                        code="EMPTY_OBSERVATION_ID",
                        message="Uma observação não possui identificador.",
                    )
                )
                continue
            if observation.observation_id in seen_observations:
                problems.append(
                    ProvenanceProblem(
                        code="DUPLICATE_OBSERVATION_ID",
                        message="O identificador da observação está duplicado.",
                        observation_id=observation.observation_id,
                    )
                )
            seen_observations.add(observation.observation_id)

            assessment = catalog.get(observation.statement_id)
            if assessment is None:
                problems.append(
                    ProvenanceProblem(
                        code="UNKNOWN_STATEMENT",
                        message="A observação cita um trecho ausente das evidências recuperadas.",
                        observation_id=observation.observation_id,
                    )
                )
                continue
            evidence = assessment.evidence
            checks = (
                (
                    observation.pmid == evidence.pmid,
                    "PMID_MISMATCH",
                    "O PMID citado não corresponde ao trecho recuperado.",
                ),
                (
                    _normalize(observation.quote) == _normalize(evidence.text),
                    "QUOTE_MISMATCH",
                    "A citação não reproduz exatamente o trecho recuperado.",
                ),
                (
                    observation.source_url == evidence.source_url,
                    "SOURCE_URL_MISMATCH",
                    "A URL citada não corresponde à fonte do trecho.",
                ),
                (
                    observation.relation is assessment.relation,
                    "RELATION_MISMATCH",
                    "A relação citada difere da classificação registrada.",
                ),
                (
                    assessment.relation is not RelationLabel.UNCERTAIN,
                    "UNCERTAIN_EVIDENCE",
                    "Uma classificação incerta não pode corroborar a revisão.",
                ),
            )
            for valid, code, message in checks:
                if not valid:
                    problems.append(
                        ProvenanceProblem(
                            code=code,
                            message=message,
                            observation_id=observation.observation_id,
                        )
                    )
        return tuple(problems)

    @staticmethod
    def _critique_problems(
        draft: ResearchDraft,
        critique: AdversarialCritique,
    ) -> tuple[ProvenanceProblem, ...]:
        problems: list[ProvenanceProblem] = []
        observation_ids = {item.observation_id for item in draft.observations}
        if not critique.model_name.strip() or not critique.prompt_version.strip():
            problems.append(
                ProvenanceProblem(
                    code="MISSING_CRITIC_METADATA",
                    message="O crítico não informou modelo e versão do prompt.",
                )
            )
        for issue in critique.issues:
            if issue.observation_id and issue.observation_id not in observation_ids:
                problems.append(
                    ProvenanceProblem(
                        code="UNKNOWN_CRITIQUE_TARGET",
                        message="O crítico aponta uma observação que não existe no rascunho.",
                        observation_id=issue.observation_id,
                    )
                )
        return tuple(problems)

    def review(
        self,
        claim: str,
        assessments: Sequence[EvidenceAssessment],
        report: EvidenceReport,
    ) -> AdversarialReviewResult:
        """Executa os agentes e aplica uma política determinística de segurança."""

        self._validate_context(claim, assessments, report)
        draft = self._researcher.research(claim, assessments, report)
        critique = self._critic.critique(claim, assessments, report, draft)
        problems = self._provenance_problems(draft, assessments) + self._critique_problems(
            draft, critique
        )
        cited_article_count = len(
            {
                observation.pmid
                for observation in draft.observations
                if observation.pmid.strip()
            }
        )

        if report.conclusion in {
            ReportConclusion.INSUFFICIENT_EVIDENCE,
            ReportConclusion.INCONCLUSIVE,
        }:
            status = ReviewStatus.INSUFFICIENT
            rationale = (
                "O relatório-base não sustenta uma conclusão; concordância entre agentes "
                "não pode aumentar a força da evidência."
            )
        elif problems:
            status = ReviewStatus.INSUFFICIENT
            rationale = "A proveniência ou a estrutura das alegações automáticas falhou."
        elif cited_article_count < self._minimum_cited_articles:
            status = ReviewStatus.INSUFFICIENT
            rationale = (
                f"Foram citados {cited_article_count} artigos independentes; o mínimo "
                f"configurado é {self._minimum_cited_articles}."
            )
        elif any(issue.severity is IssueSeverity.CRITICAL for issue in critique.issues):
            status = ReviewStatus.DISPUTED
            rationale = "O crítico identificou ao menos um problema crítico no rascunho."
        elif report.conclusion is ReportConclusion.CONFLICTING_EVIDENCE:
            status = ReviewStatus.DISPUTED
            rationale = "O relatório-base preserva conflito entre as evidências analisadas."
        else:
            status = ReviewStatus.CORROBORATED
            rationale = (
                "As observações foram corroboradas apenas no conjunto recuperado, com "
                "proveniência válida e sem objeção crítica impeditiva."
            )

        return AdversarialReviewResult(
            status=status,
            rationale=rationale,
            draft=draft,
            critique=critique,
            provenance_problems=problems,
            cited_article_count=cited_article_count,
        )
