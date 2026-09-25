import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    ArticleQualityProfile,
    EvidenceAssessment,
    EvidenceDirection,
    EvidenceStatement,
    EvidenceStrength,
    QualityLevel,
    RelationLabel,
    RelationProbabilities,
    RetrievalError,
    SynthesisConfig,
    synthesize_evidence,
)


def assessment(
    pmid: str,
    relation: RelationLabel,
    support: float,
    contradiction: float,
    neutral: float,
    index: int = 1,
) -> EvidenceAssessment:
    evidence = EvidenceStatement(
        statement_id=f"statement:{pmid}:{index}",
        text="Scientific evidence statement.",
        extraction_score=1.0,
        matched_claim_terms=("evidence",),
        hybrid_rank=index,
        sentence_index=index,
        chunk_id=f"chunk:{pmid}:{index}",
        pmid=pmid,
        pmcid=f"PMC{pmid}",
        doi=f"10.1000/{pmid}",
        section="Results",
        source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    )
    return EvidenceAssessment(
        pair_id=f"pair:{pmid}:{index}",
        relation=relation,
        model_relation=relation,
        confidence=max(support, contradiction, neutral),
        margin=0.5,
        probabilities=RelationProbabilities(support, contradiction, neutral),
        rationale="Controlled result.",
        model_name="controlled-nli",
        claim="Health claim.",
        evidence=evidence,
    )


def quality(pmid: str, level: QualityLevel = QualityLevel.MODERATE):
    return ArticleQualityProfile(
        pmid=pmid,
        level=level,
        study_design="Controlled design",
        rationale="Quality assessed for a controlled test.",
        source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    )


class EvidenceSynthesisTests(unittest.TestCase):
    def test_one_article_has_direction_but_insufficient_strength(self) -> None:
        result = synthesize_evidence(
            [assessment("1", RelationLabel.SUPPORTS, 0.8, 0.1, 0.1)],
            [quality("1")],
        )

        self.assertEqual(result.direction, EvidenceDirection.SUPPORTS)
        self.assertEqual(result.strength, EvidenceStrength.INSUFFICIENT)
        self.assertEqual(result.article_count, 1)
        self.assertIn("apenas 1 artigo", result.rationale)

    def test_aggregates_within_article_before_combining_articles(self) -> None:
        many_supporting_chunks = [
            assessment("1", RelationLabel.SUPPORTS, 0.8, 0.1, 0.1, index)
            for index in range(1, 11)
        ]
        one_contradicting_chunk = assessment(
            "2", RelationLabel.CONTRADICTS, 0.1, 0.8, 0.1
        )

        result = synthesize_evidence(
            [*many_supporting_chunks, one_contradicting_chunk],
            [quality("1"), quality("2")],
        )

        self.assertAlmostEqual(result.support_probability, 0.45)
        self.assertAlmostEqual(result.contradiction_probability, 0.45)
        self.assertEqual(result.direction, EvidenceDirection.MIXED)
        self.assertTrue(result.has_conflict)

    def test_reports_internal_article_conflict(self) -> None:
        result = synthesize_evidence(
            [
                assessment("1", RelationLabel.SUPPORTS, 0.8, 0.1, 0.1, 1),
                assessment("1", RelationLabel.CONTRADICTS, 0.1, 0.8, 0.1, 2),
            ],
            [quality("1")],
        )

        self.assertEqual(result.articles[0].direction, EvidenceDirection.MIXED)
        self.assertTrue(result.articles[0].has_internal_conflict)
        self.assertTrue(result.has_conflict)

    def test_two_consistent_moderate_quality_articles_reach_moderate_strength(self) -> None:
        result = synthesize_evidence(
            [
                assessment("1", RelationLabel.SUPPORTS, 0.8, 0.1, 0.1),
                assessment("2", RelationLabel.SUPPORTS, 0.7, 0.1, 0.2),
            ],
            [quality("1"), quality("2")],
        )

        self.assertEqual(result.direction, EvidenceDirection.SUPPORTS)
        self.assertEqual(result.strength, EvidenceStrength.MODERATE)
        self.assertFalse(result.has_conflict)

    def test_unclear_quality_limits_strength(self) -> None:
        result = synthesize_evidence(
            [
                assessment("1", RelationLabel.SUPPORTS, 0.8, 0.1, 0.1),
                assessment("2", RelationLabel.SUPPORTS, 0.8, 0.1, 0.1),
            ],
            [quality("1"), quality("2", QualityLevel.UNCLEAR)],
        )

        self.assertEqual(result.strength, EvidenceStrength.LOW)

    def test_rejects_invalid_or_missing_quality_profiles(self) -> None:
        item = assessment("1", RelationLabel.SUPPORTS, 0.8, 0.1, 0.1)
        with self.assertRaises(RetrievalError):
            SynthesisConfig(minimum_articles=1)
        with self.assertRaises(RetrievalError):
            synthesize_evidence([], [])
        with self.assertRaises(RetrievalError):
            synthesize_evidence([item], [])
        with self.assertRaises(RetrievalError):
            synthesize_evidence([item], [quality("1"), quality("1")])


if __name__ == "__main__":
    unittest.main()
