import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    ArticleContent,
    ChunkingConfig,
    ChunkingError,
    ContentSection,
    chunk_article_content,
)


def full_text_content() -> ArticleContent:
    return ArticleContent(
        pmid="123",
        pmcid="PMC123",
        doi="10.1000/test",
        abstract="Resumo que não deve ser duplicado quando há texto completo.",
        full_text="Conteúdo completo disponível.",
        sections=(
            ContentSection("Methods", "one two three four five six seven eight"),
            ContentSection("Results", "alpha beta gamma delta"),
        ),
        access_level="FULL_TEXT",
        pubmed_url="https://pubmed.ncbi.nlm.nih.gov/123/",
        pmc_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC123/",
    )


class ChunkingTests(unittest.TestCase):
    def test_chunks_each_section_with_overlap_and_provenance(self) -> None:
        chunks = chunk_article_content(
            full_text_content(),
            ChunkingConfig(max_words=5, overlap_words=2),
        )

        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].text, "one two three four five")
        self.assertEqual(chunks[1].text, "four five six seven eight")
        self.assertEqual((chunks[1].word_start, chunks[1].word_end), (3, 8))
        self.assertEqual(chunks[2].section, "Results")
        self.assertEqual(chunks[2].chunk_index, 1)
        self.assertTrue(all(chunk.source_kind == "PMC_FULL_TEXT" for chunk in chunks))
        self.assertTrue(all(chunk.pmcid == "PMC123" for chunk in chunks))

    def test_generates_stable_unique_identifiers(self) -> None:
        first_run = chunk_article_content(full_text_content(), ChunkingConfig(5, 2))
        second_run = chunk_article_content(full_text_content(), ChunkingConfig(5, 2))

        first_ids = [chunk.chunk_id for chunk in first_run]
        second_ids = [chunk.chunk_id for chunk in second_run]
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(len(first_ids), len(set(first_ids)))

    def test_falls_back_to_abstract(self) -> None:
        content = ArticleContent(
            pmid="456",
            pmcid=None,
            doi=None,
            abstract="one two three four five six",
            full_text=None,
            sections=(),
            access_level="ABSTRACT_ONLY",
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/456/",
            pmc_url=None,
        )

        chunks = chunk_article_content(content, ChunkingConfig(4, 1))

        self.assertEqual([chunk.section for chunk in chunks], ["Resumo", "Resumo"])
        self.assertTrue(all(chunk.source_kind == "PUBMED_ABSTRACT" for chunk in chunks))
        self.assertEqual(chunks[0].source_url, content.pubmed_url)

    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaises(ChunkingError):
            ChunkingConfig(max_words=10, overlap_words=10)

    def test_rejects_content_without_text(self) -> None:
        empty_content = ArticleContent(
            pmid="789",
            pmcid=None,
            doi=None,
            abstract=None,
            full_text=None,
            sections=(),
            access_level="ABSTRACT_ONLY",
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/789/",
            pmc_url=None,
        )

        with self.assertRaises(ChunkingError):
            chunk_article_content(empty_content)


if __name__ == "__main__":
    unittest.main()
