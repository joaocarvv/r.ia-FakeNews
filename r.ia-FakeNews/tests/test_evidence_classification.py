import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    ClaimEvidencePair,
    ClassificationConfig,
    EvidenceStatement,
    RelationLabel,
    RetrievalError,
    classify_claim_evidence_pairs,
)


class ControlledClassifier:
    def __init__(self, scores):
        self.scores = scores

    @property
    def name(self):
        return "controlled-nli"

    def predict(self, premise, hypothesis):
        return self.scores


def pair() -> ClaimEvidencePair:
    statement = EvidenceStatement(
        statement_id="statement:1",
        text="Coffee intake was associated with lower prostate cancer risk.",
        extraction_score=1.0,
        matched_claim_terms=("coffee", "cancer"),
        hybrid_rank=1,
        sentence_index=1,
        chunk_id="chunk:1",
        pmid="123",
        pmcid="PMC123",
        doi="10.1000/test",
        section="Results",
        source_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC123/",
    )
    return ClaimEvidencePair(
        pair_id="pair:1",
        claim="Café reduz o risco de câncer de próstata.",
        evidence=statement,
    )


class EvidenceClassificationTests(unittest.TestCase):
    def test_classifies_support_and_preserves_audit_fields(self) -> None:
        result = classify_claim_evidence_pairs(
            [pair()],
            ControlledClassifier(
                {"entailment": 0.82, "contradiction": 0.08, "neutral": 0.10}
            ),
        )[0]

        self.assertEqual(result.relation, RelationLabel.SUPPORTS)
        self.assertEqual(result.model_relation, RelationLabel.SUPPORTS)
        self.assertEqual(result.model_name, "controlled-nli")
        self.assertEqual(result.evidence.pmid, "123")
        self.assertAlmostEqual(result.margin, 0.72)
        self.assertIn("limites mínimos", result.rationale)

    def test_classifies_contradiction(self) -> None:
        result = classify_claim_evidence_pairs(
            [pair()],
            ControlledClassifier(
                {"entailment": 0.05, "contradiction": 0.90, "neutral": 0.05}
            ),
        )[0]

        self.assertEqual(result.relation, RelationLabel.CONTRADICTS)

    def test_classifies_neutral(self) -> None:
        result = classify_claim_evidence_pairs(
            [pair()],
            ControlledClassifier(
                {"entailment": 0.10, "contradiction": 0.10, "neutral": 0.80}
            ),
        )[0]

        self.assertEqual(result.relation, RelationLabel.NEUTRAL)

    def test_marks_low_confidence_or_small_margin_as_uncertain(self) -> None:
        low_confidence = classify_claim_evidence_pairs(
            [pair()],
            ControlledClassifier(
                {"entailment": 0.50, "contradiction": 0.20, "neutral": 0.30}
            ),
        )[0]
        small_margin = classify_claim_evidence_pairs(
            [pair()],
            ControlledClassifier(
                {"entailment": 0.51, "contradiction": 0.00, "neutral": 0.49}
            ),
            ClassificationConfig(minimum_confidence=0.50, minimum_margin=0.10),
        )[0]

        self.assertEqual(low_confidence.relation, RelationLabel.UNCERTAIN)
        self.assertEqual(small_margin.relation, RelationLabel.UNCERTAIN)
        self.assertIn("marcado como incerto", small_margin.rationale)

    def test_normalizes_probabilities(self) -> None:
        result = classify_claim_evidence_pairs(
            [pair()],
            ControlledClassifier(
                {"entailment": 8, "contradiction": 1, "neutral": 1}
            ),
        )[0]

        total = (
            result.probabilities.support
            + result.probabilities.contradiction
            + result.probabilities.neutral
        )
        self.assertAlmostEqual(total, 1.0)
        self.assertAlmostEqual(result.probabilities.support, 0.8)

    def test_rejects_invalid_configuration_and_classifier_outputs(self) -> None:
        with self.assertRaises(RetrievalError):
            ClassificationConfig(minimum_confidence=1.1)
        with self.assertRaises(RetrievalError):
            classify_claim_evidence_pairs([], ControlledClassifier({}))
        with self.assertRaises(RetrievalError):
            classify_claim_evidence_pairs(
                [pair()],
                ControlledClassifier({"entailment": 1, "neutral": 0}),
            )
        with self.assertRaises(RetrievalError):
            classify_claim_evidence_pairs(
                [pair()],
                ControlledClassifier(
                    {"entailment": float("nan"), "contradiction": 0, "neutral": 1}
                ),
            )


if __name__ == "__main__":
    unittest.main()
