import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.federated_search import ScientificWork, SourceRank
from fatofake.scientific_search import ClaimRelevanceReranker, expand_scientific_queries


def work(title, identifier, *, source="PubMed", rank=1):
    query = "hydrostatic pressure rhodopsin hydration"
    return ScientificWork(
        title=title,
        authors=(),
        journal=None,
        publication_date="2024",
        doi=f"10.1000/{identifier}",
        pmid=identifier,
        url=f"https://example.org/{identifier}",
        matched_queries=(query,),
        sources=(source,),
        source_ids=((source, identifier),),
        source_ranks=(SourceRank(source, query, rank),),
        retrieval_score=1 / (60 + rank),
    )


class ScientificSearchTests(unittest.TestCase):
    def test_expansion_records_theme_mesh_review_doi_and_author(self):
        expanded = expand_scientific_queries(
            "Hydrostatic pressure changes rhodopsin hydration.",
            ("hydrostatic pressure rhodopsin hydration",),
            seed_doi="10.1000/rhodopsin",
            seed_authors=("Ana Silva",),
        )

        strategies = {item.strategy for item in expanded}
        self.assertTrue(
            {"THEMATIC", "MESH_CANDIDATES", "EVIDENCE_SYNTHESIS", "SEED_DOI", "SEED_AUTHOR"}
            <= strategies
        )
        self.assertLessEqual(len(expanded), 6)

    def test_reranker_rejects_one_word_overlap_and_keeps_direct_answer(self):
        relevant = work(
            "Hydrostatic pressure controls hydration and activation of rhodopsin",
            "1",
        )
        lexical_noise = work(
            "Hydrostatic pressure during coffee extraction",
            "2",
            rank=2,
        )

        ranked = ClaimRelevanceReranker().rank(
            "Hydrostatic pressure changes rhodopsin hydration.",
            (lexical_noise, relevant),
        )

        self.assertTrue(ranked[0].accepted)
        self.assertEqual(ranked[0].work, relevant)
        rejected = next(item for item in ranked if item.work == lexical_noise)
        self.assertFalse(rejected.accepted)
        self.assertIn("cobertura temática insuficiente", rejected.reasons[-1])

    def test_graph_neighbor_still_requires_one_claim_concept(self):
        unrelated = work(
            "Coffee extraction temperature",
            "3",
            source="OpenAlex relacionados",
        )

        result = ClaimRelevanceReranker().rank(
            "Hydrostatic pressure changes rhodopsin hydration.",
            (unrelated,),
        )[0]

        self.assertFalse(result.accepted)


if __name__ == "__main__":
    unittest.main()
