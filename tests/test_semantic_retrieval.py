import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import EvidenceChunk, RetrievalError, SemanticIndex


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


class ControlledEncoder:
    name = "controlled-test-encoder"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]


class SemanticIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = [
            chunk("1", "coffee consumption and prostate cancer risk"),
            chunk("2", "physical exercise and cardiovascular health"),
            chunk("3", "coffee preparation method"),
        ]
        self.encoder = ControlledEncoder(
            {
                self.chunks[0].text: [1.0, 0.0],
                self.chunks[1].text: [0.0, 1.0],
                self.chunks[2].text: [0.8, 0.6],
                "café e risco de câncer de próstata": [1.0, 0.0],
            }
        )

    def test_ranks_by_cosine_similarity(self) -> None:
        index = SemanticIndex(self.chunks, self.encoder)

        results = index.search("café e risco de câncer de próstata", top_k=2)

        self.assertEqual([result.chunk.chunk_id for result in results], ["1", "3"])
        self.assertAlmostEqual(results[0].score, 1.0)
        self.assertEqual(index.model_name, "controlled-test-encoder")

    def test_breaks_ties_by_chunk_identifier(self) -> None:
        tied_chunks = [chunk("2", "second"), chunk("1", "first")]
        encoder = ControlledEncoder(
            {"second": [1.0, 0.0], "first": [1.0, 0.0], "query": [1.0, 0.0]}
        )

        results = SemanticIndex(tied_chunks, encoder).search("query")

        self.assertEqual([result.chunk.chunk_id for result in results], ["1", "2"])

    def test_applies_minimum_score(self) -> None:
        index = SemanticIndex(self.chunks, self.encoder)

        results = index.search(
            "café e risco de câncer de próstata",
            minimum_score=0.9,
        )

        self.assertEqual([result.chunk.chunk_id for result in results], ["1"])

    def test_rejects_invalid_query_and_limits(self) -> None:
        index = SemanticIndex(self.chunks, self.encoder)
        with self.assertRaises(RetrievalError):
            index.search(" ")
        with self.assertRaises(RetrievalError):
            index.search("café e risco de câncer de próstata", top_k=0)
        with self.assertRaises(RetrievalError):
            index.search("café e risco de câncer de próstata", minimum_score=2)

    def test_rejects_invalid_embeddings(self) -> None:
        with self.assertRaises(RetrievalError):
            SemanticIndex([chunk("1", "text")], ControlledEncoder({"text": [0, 0]}))


if __name__ == "__main__":
    unittest.main()
