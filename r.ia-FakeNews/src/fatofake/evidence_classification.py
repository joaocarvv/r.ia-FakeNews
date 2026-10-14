"""Classifica a relação entre uma alegação e evidências científicas."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol, Sequence

from .evidence_extraction import ClaimEvidencePair, EvidenceStatement
from .retrieval import RetrievalError


DEFAULT_NLI_MODEL = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"
_NLI_LABELS = ("entailment", "contradiction", "neutral")


class RelationLabel(str, Enum):
    """Relações apresentadas pelo sistema, incluindo incerteza explícita."""

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"
    UNCERTAIN = "UNCERTAIN"


class NliClassifier(Protocol):
    """Contrato mínimo para um classificador de inferência textual."""

    @property
    def name(self) -> str:
        """Identificador auditável do modelo usado."""

    def predict(self, premise: str, hypothesis: str) -> Mapping[str, float]:
        """Retorna probabilidades para entailment, contradiction e neutral."""


class TransformersNliClassifier:
    """Adaptador para modelos NLI da biblioteca Transformers."""

    def __init__(self, model_name: str = DEFAULT_NLI_MODEL) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as error:
            raise RetrievalError(
                "transformers e torch são necessários; instale requirements.txt."
            ) from error

        self._name = model_name
        self._torch = torch
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
        except Exception as error:
            raise RetrievalError(
                f"Não foi possível carregar o modelo NLI {model_name!r}."
            ) from error
        self._model.eval()
        self._label_indices = self._resolve_label_indices(self._model.config.id2label)

    @staticmethod
    def _resolve_label_indices(id2label: Mapping[int, str]) -> dict[str, int]:
        resolved: dict[str, int] = {}
        for raw_index, raw_label in id2label.items():
            label = str(raw_label).casefold()
            for expected in _NLI_LABELS:
                if expected in label:
                    resolved[expected] = int(raw_index)
        if set(resolved) != set(_NLI_LABELS):
            raise RetrievalError(
                "O modelo NLI não identifica claramente entailment, contradiction e neutral."
            )
        return resolved

    @property
    def name(self) -> str:
        return self._name

    def predict(self, premise: str, hypothesis: str) -> Mapping[str, float]:
        if not premise.strip() or not hypothesis.strip():
            raise RetrievalError("Premissa e hipótese não podem estar vazias.")
        encoded = self._tokenizer(
            premise,
            hypothesis,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )
        with self._torch.inference_mode():
            logits = self._model(**encoded).logits[0]
            probabilities = self._torch.softmax(logits, dim=-1).tolist()
        return {
            label: float(probabilities[index])
            for label, index in self._label_indices.items()
        }


@dataclass(frozen=True)
class ClassificationConfig:
    """Limites usados para não esconder classificações ambíguas."""

    minimum_confidence: float = 0.60
    minimum_margin: float = 0.10

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_confidence <= 1:
            raise RetrievalError("minimum_confidence deve estar entre 0 e 1.")
        if not 0 <= self.minimum_margin <= 1:
            raise RetrievalError("minimum_margin deve estar entre 0 e 1.")


@dataclass(frozen=True)
class RelationProbabilities:
    """Probabilidades normalizadas nas três relações previstas pelo NLI."""

    support: float
    contradiction: float
    neutral: float


@dataclass(frozen=True)
class EvidenceAssessment:
    """Resultado auditável de um par, sem convertê-lo em veredito de verdade."""

    pair_id: str
    relation: RelationLabel
    model_relation: RelationLabel
    confidence: float
    margin: float
    probabilities: RelationProbabilities
    rationale: str
    model_name: str
    claim: str
    evidence: EvidenceStatement


def _validated_probabilities(scores: Mapping[str, float]) -> RelationProbabilities:
    if not all(label in scores for label in _NLI_LABELS):
        raise RetrievalError(
            "O classificador deve retornar entailment, contradiction e neutral."
        )
    values = {label: float(scores[label]) for label in _NLI_LABELS}
    if not all(math.isfinite(value) and value >= 0 for value in values.values()):
        raise RetrievalError("O classificador retornou probabilidades inválidas.")
    total = sum(values.values())
    if total <= 0:
        raise RetrievalError("A soma das probabilidades deve ser maior que zero.")
    return RelationProbabilities(
        support=values["entailment"] / total,
        contradiction=values["contradiction"] / total,
        neutral=values["neutral"] / total,
    )


def _rationale(
    model_relation: RelationLabel,
    confidence: float,
    margin: float,
    relation: RelationLabel,
    config: ClassificationConfig,
) -> str:
    names = {
        RelationLabel.SUPPORTS: "apoio",
        RelationLabel.CONTRADICTS: "contradição",
        RelationLabel.NEUTRAL: "neutralidade",
    }
    base = (
        f"O modelo NLI atribuiu maior probabilidade a {names[model_relation]} "
        f"({confidence:.1%}; margem de {margin:.1%})."
    )
    if relation is RelationLabel.UNCERTAIN:
        return (
            f"{base} O resultado foi marcado como incerto porque não atingiu "
            f"simultaneamente confiança de {config.minimum_confidence:.0%} e "
            f"margem de {config.minimum_margin:.0%}."
        )
    return f"{base} Os limites mínimos de confiança e margem foram atendidos."


def classify_claim_evidence_pairs(
    pairs: Sequence[ClaimEvidencePair],
    classifier: NliClassifier,
    config: ClassificationConfig | None = None,
) -> tuple[EvidenceAssessment, ...]:
    """Classifica pares com NLI e preserva probabilidades, modelo e proveniência."""

    if not pairs:
        raise RetrievalError("Ao menos um par alegação-evidência é necessário.")
    active_config = config or ClassificationConfig()
    assessments: list[EvidenceAssessment] = []
    label_map = {
        "support": RelationLabel.SUPPORTS,
        "contradiction": RelationLabel.CONTRADICTS,
        "neutral": RelationLabel.NEUTRAL,
    }

    for pair in pairs:
        probabilities = _validated_probabilities(
            classifier.predict(pair.evidence.text, pair.claim)
        )
        ranked = sorted(
            (
                (probabilities.support, "support"),
                (probabilities.contradiction, "contradiction"),
                (probabilities.neutral, "neutral"),
            ),
            key=lambda item: (-item[0], item[1]),
        )
        confidence, raw_relation = ranked[0]
        margin = confidence - ranked[1][0]
        model_relation = label_map[raw_relation]
        relation = (
            model_relation
            if confidence >= active_config.minimum_confidence
            and margin >= active_config.minimum_margin
            else RelationLabel.UNCERTAIN
        )
        assessments.append(
            EvidenceAssessment(
                pair_id=pair.pair_id,
                relation=relation,
                model_relation=model_relation,
                confidence=confidence,
                margin=margin,
                probabilities=probabilities,
                rationale=_rationale(
                    model_relation,
                    confidence,
                    margin,
                    relation,
                    active_config,
                ),
                model_name=classifier.name,
                claim=pair.claim,
                evidence=pair.evidence,
            )
        )
    return tuple(assessments)
