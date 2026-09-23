import sys
import unittest
from dataclasses import dataclass
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    EvidenceChunk,
    HybridConfig,
    HybridIndex,
    RetrievalError,
)


def chunk(chunk_id: str) -> EvidenceChunk:
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
        word_end=1,
        text=f"text {chunk_id}",
    )


@dataclass(frozen=True)
class StubResult:
    rank: int
    chunk: EvidenceChunk


class StubIndex:
    def __init__(self, chunks: list[EvidenceChunk], ranking: list[str]) -> None:
        self.chunks = tuple(chunks)
        chunks_by_id = {item.chunk_id: item for item in chunks}
        self.results = tuple(
            StubResult(rank, chunks_by_id[chunk_id])
            for rank, chunk_id in enumerate(ranking, start=1)
        )

    def search(self, query: str, *, top_k: int) -> tuple[StubResult, ...]:
        return self.results[:top_k]


class HybridIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = [chunk("1"), chunk("2"), chunk("3"), chunk("4")]

    def test_promotes_chunks_found_by_both_methods(self) -> None:
        lexical = StubIndex(self.chunks, ["1", "2", "3"])
        semantic = StubIndex(self.chunks, ["4", "2", "3"])

        results = HybridIndex(lexical, semantic).search("query", top_k=3)

        self.assertEqual(results[0].chunk.chunk_id, "2")
        self.assertEqual(results[0].lexical_rank, 2)
        self.assertEqual(results[0].semantic_rank, 2)
        self.assertGreater(results[0].score, results[1].score)

    def test_records_each_rrf_contribution(self) -> None:
        lexical = StubIndex(self.chunks, ["1", "2"])
        semantic = StubIndex(self.chunks, ["2", "3"])
        config = HybridConfig(lexical_weight=2, semantic_weight=1, rrf_k=10)

        result = HybridIndex(lexical, semantic, config).search("query", top_k=1)[0]

        self.assertEqual(result.chunk.chunk_id, "2")
        self.assertAlmostEqual(result.lexical_contribution, 2 / 12)
        self.assertAlmostEqual(result.semantic_contribution, 1 / 11)
        self.assertAlmostEqual(
            result.score,
            result.lexical_contribution + result.semantic_contribution,
        )

    def test_uses_chunk_identifier_as_deterministic_tie_breaker(self) -> None:
        lexical = StubIndex(self.chunks, ["2", "1"])
        semantic = StubIndex(self.chunks, ["1", "2"])

        results = HybridIndex(lexical, semantic).search("query", top_k=2)

        self.assertEqual([result.chunk.chunk_id for result in results], ["1", "2"])

    def test_rejects_different_collections(self) -> None:
        lexical = StubIndex(self.chunks, ["1"])
        semantic = StubIndex(self.chunks[:-1], ["1"])

        with self.assertRaises(RetrievalError):
            HybridIndex(lexical, semantic)

    def test_rejects_invalid_configuration_and_query(self) -> None:
        with self.assertRaises(RetrievalError):
            HybridConfig(lexical_weight=0, semantic_weight=0)
        with self.assertRaises(RetrievalError):
            HybridConfig(rrf_k=0)

        index = HybridIndex(
            StubIndex(self.chunks, ["1"]),
            StubIndex(self.chunks, ["1"]),
        )
        with self.assertRaises(RetrievalError):
            index.search(" ")
        with self.assertRaises(RetrievalError):
            index.search("query", top_k=0)


if __name__ == "__main__":
    unittest.main()
