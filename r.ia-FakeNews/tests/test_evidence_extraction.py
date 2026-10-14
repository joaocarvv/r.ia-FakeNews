import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    EvidenceChunk,
    ExtractionConfig,
    HybridRetrievedChunk,
    RetrievalError,
    build_claim_evidence_pairs,
    extract_evidence_statements,
)


def ranked_chunk(rank: int, chunk_id: str, text: str) -> HybridRetrievedChunk:
    chunk = EvidenceChunk(
        chunk_id=chunk_id,
        pmid="123",
        pmcid="PMC123",
        doi="10.1000/test",
        source_kind="PMC_FULL_TEXT",
        source_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC123/",
        section="Conclusions",
        section_index=1,
        chunk_index=rank,
        word_start=0,
        word_end=len(text.split()),
        text=text,
    )
    return HybridRetrievedChunk(
        rank=rank,
        score=1 / rank,
        lexical_rank=rank,
        semantic_rank=rank,
        lexical_contribution=0.5 / rank,
        semantic_contribution=0.5 / rank,
        chunk=chunk,
    )


class EvidenceExtractionTests(unittest.TestCase):
    def test_extracts_related_sentence_with_provenance(self) -> None:
        chunks = [
            ranked_chunk(
                1,
                "1",
                "Coffee consumption was associated with reduced prostate cancer risk. "
                "Further research should investigate biological mechanisms.",
            )
        ]

        statements = extract_evidence_statements(
            "Café altera o risco de câncer de próstata.",
            chunks,
        )

        self.assertEqual(statements[0].chunk_id, "1")
        self.assertEqual(statements[0].pmcid, "PMC123")
        self.assertIn("cancer", statements[0].matched_claim_terms)
        self.assertNotIn("prostata", statements[0].matched_claim_terms)

    def test_orders_by_term_coverage_then_hybrid_rank(self) -> None:
        chunks = [
            ranked_chunk(1, "1", "Coffee was evaluated in a large prospective cohort study."),
            ranked_chunk(
                2,
                "2",
                "Coffee intake was associated with lower prostate cancer risk in men.",
            ),
        ]

        statements = extract_evidence_statements(
            "Café altera o risco de câncer de próstata.",
            chunks,
        )

        self.assertEqual(statements[0].chunk_id, "2")

    def test_removes_duplicate_sentences_from_overlapping_chunks(self) -> None:
        repeated = "Coffee intake was associated with prostate cancer risk in adult men."
        chunks = [ranked_chunk(1, "1", repeated), ranked_chunk(2, "2", repeated)]

        statements = extract_evidence_statements(
            "Café e risco de câncer de próstata.",
            chunks,
        )

        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0].chunk_id, "1")

    def test_separates_sentences_with_attached_numeric_citations(self) -> None:
        chunks = [
            ranked_chunk(
                1,
                "1",
                "Prior studies were inconsistent.22 23 Coffee intake was associated "
                "with reduced prostate cancer risk.",
            )
        ]

        statements = extract_evidence_statements(
            "Café e risco de câncer de próstata.",
            chunks,
        )

        self.assertEqual(
            statements[0].text,
            "Coffee intake was associated with reduced prostate cancer risk.",
        )

    def test_excludes_objectives_and_hypotheses(self) -> None:
        chunks = [
            ranked_chunk(
                1,
                "1",
                "It was hypothesised that coffee reduced prostate cancer risk. "
                "The objective of this study was to evaluate prostate cancer risk. "
                "Forest plot for coffee consumption and prostate cancer risk. "
                "Coffee intake was associated with reduced prostate cancer risk in men.",
            )
        ]

        statements = extract_evidence_statements(
            "Café e risco de câncer de próstata.",
            chunks,
        )

        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].text.startswith("Coffee intake"))

    def test_preserves_decimal_results_while_removing_citations(self) -> None:
        chunks = [
            ranked_chunk(
                1,
                "1",
                "Prior evidence was inconsistent.22 The pooled prostate cancer "
                "risk ratio was 0.95 with a 95% confidence interval.",
            )
        ]

        statements = extract_evidence_statements(
            "Café e risco de câncer de próstata.",
            chunks,
        )

        self.assertIn("0.95", statements[0].text)
        self.assertNotIn(".22", statements[0].text)

    def test_builds_stable_pending_pairs(self) -> None:
        chunks = [
            ranked_chunk(
                1,
                "1",
                "Coffee intake was associated with prostate cancer risk in adult men.",
            )
        ]
        claim = "Café e risco de câncer de próstata."
        statements = extract_evidence_statements(claim, chunks)

        first = build_claim_evidence_pairs(claim, statements)
        second = build_claim_evidence_pairs(claim, statements)

        self.assertEqual(first, second)
        self.assertEqual(first[0].assessment_status, "PENDING")
        self.assertEqual(first[0].claim, claim)

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(RetrievalError):
            ExtractionConfig(max_statements=0)
        with self.assertRaises(RetrievalError):
            ExtractionConfig(min_words=10, max_words=5)
        with self.assertRaises(RetrievalError):
            extract_evidence_statements("claim", [])
        with self.assertRaises(RetrievalError):
            build_claim_evidence_pairs("claim", [])


if __name__ == "__main__":
    unittest.main()
