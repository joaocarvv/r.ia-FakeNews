import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import Bm25Config, Bm25Index, EvidenceChunk, RetrievalError, tokenize


def chunk(chunk_id: str, text: str) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=chunk_id,
        pmid="123",
        pmcid="PMC123",
        doi="10.1000/test",
        source_kind="PMC_FULL_TEXT",
        source_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC123/",
        section="Results",
        section_index=1,
        chunk_index=int(chunk_id),
        word_start=0,
        word_end=len(text.split()),
        text=text,
    )


class Bm25IndexTests(unittest.TestCase):
    def test_ranks_the_most_relevant_chunk_first(self) -> None:
        index = Bm25Index(
            [
                chunk("1", "coffee consumption and prostate cancer risk"),
                chunk("2", "coffee preparation methods"),
                chunk("3", "exercise and cardiovascular health"),
            ]
        )

        results = index.search("coffee prostate cancer risk")

        self.assertEqual(results[0].chunk.chunk_id, "1")
        self.assertEqual(results[0].rank, 1)
        self.assertEqual(
            results[0].matched_terms,
            ("coffee", "prostate", "cancer", "risk"),
        )
        self.assertGreater(results[0].score, results[1].score)

    def test_breaks_score_ties_by_stable_chunk_identifier(self) -> None:
        index = Bm25Index([chunk("2", "coffee"), chunk("1", "coffee")])

        results = index.search("coffee")

        self.assertEqual([result.chunk.chunk_id for result in results], ["1", "2"])

    def test_returns_no_result_when_there_is_no_match(self) -> None:
        index = Bm25Index([chunk("1", "coffee and health")])

        self.assertEqual(index.search("unrelated"), ())

    def test_normalizes_case_and_accents(self) -> None:
        self.assertEqual(tokenize("CÂNCER de Próstata"), ("cancer", "de", "prostata"))
        index = Bm25Index([chunk("1", "Câncer de próstata")])
        self.assertEqual(index.search("cancer PROSTATA")[0].chunk.chunk_id, "1")

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(RetrievalError):
            Bm25Index([])
        with self.assertRaises(RetrievalError):
            Bm25Config(k1=0)
        with self.assertRaises(RetrievalError):
            Bm25Config(b=1.1)

        index = Bm25Index([chunk("1", "coffee")])
        with self.assertRaises(RetrievalError):
            index.search("---")
        with self.assertRaises(RetrievalError):
            index.search("coffee", top_k=0)


if __name__ == "__main__":
    unittest.main()
