import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    FederatedSearchEngine,
    ProviderSearchResult,
    Publication,
    RetrievalError,
    ScientificWork,
    SourceRank,
)
from fatofake.gemini_evidence import GeminiEvidenceAssessment
from fatofake.retrieval_preview import GenericHealthQueryPlanner, RetrievalPreviewRunner


class ProviderStub:
    def __init__(self, name, *, fail=False):
        self.name = name
        self.fail = fail
        self.queries = []

    def search(self, query, *, max_results):
        self.queries.append(query)
        if self.fail:
            raise RetrievalError("controlled failure")
        item = ScientificWork(
            title=f"Real metadata for {query}",
            authors=("Author A",),
            journal="Journal",
            publication_date="2025",
            doi=f"10.1000/{len(self.queries)}",
            pmid=str(1000 + len(self.queries)),
            url="https://example.org/real-metadata",
            matched_queries=(query,),
            sources=(self.name,),
            source_ids=((self.name, str(len(self.queries))),),
            source_ranks=(SourceRank(self.name, query, 1),),
        )
        return ProviderSearchResult(self.name, query, 1, (item,))


class RetrievalPreviewTests(unittest.TestCase):
    def test_expands_a_submitted_pubmed_article_with_related_records(self):
        class RelatedClientStub:
            def related_ids(self, pmid, *, max_results):
                self.seed = pmid
                return ("32596956",)

            def fetch_summaries(self, identifiers, matched_queries):
                return (
                    Publication(
                        pmid="32596956",
                        title="Activation of rhodopsin by water",
                        authors=("Author",),
                        journal="Journal",
                        publication_date="2020",
                        doi="10.1000/related",
                        url="https://pubmed.ncbi.nlm.nih.gov/32596956/",
                        matched_queries=matched_queries["32596956"],
                    ),
                )

        related = RelatedClientStub()
        runner = RetrievalPreviewRunner(
            FederatedSearchEngine((ProviderStub("PubMed"),)),
            related_client=related,
        )

        result = runner.analyze(
            "Water affects rhodopsin activation.",
            related_seed_pmids=("39550612",),
        )

        self.assertEqual(related.seed, "39550612")
        self.assertTrue(
            any(
                item["source"] == "PubMed relacionados"
                for item in result["search"]["query_results"]
            )
        )
        self.assertTrue(
            any(item["pmid"] == "32596956" for item in result["articles"])
        )

    def test_planner_accepts_different_health_topics(self):
        class TranslatorStub:
            def translate(self, text):
                if "vitamina" in text.casefold():
                    return "Does vitamin C reduce the duration of colds in adults?"
                return "Does sleeping less than six hours increase blood pressure?"

        planner = GenericHealthQueryPlanner(TranslatorStub())

        vitamin_queries = planner.generate_queries(
            "A vitamina C reduz a duração de resfriados em adultos?"
        )
        sleep_queries = planner.generate_queries(
            "Dormir menos de seis horas aumenta a pressão arterial?"
        )

        self.assertIn("vitamin", vitamin_queries[0].casefold())
        self.assertIn("colds", vitamin_queries[1].casefold())
        self.assertIn("sleeping", sleep_queries[0].casefold())
        self.assertNotEqual(vitamin_queries, sleep_queries)

    def test_planner_falls_back_to_original_query_when_translation_fails(self):
        class FailingTranslator:
            def translate(self, text):
                raise RuntimeError("model unavailable")

        planner = GenericHealthQueryPlanner(FailingTranslator())

        queries = planner.generate_queries(
            "A vitamina C reduz a duração de resfriados em adultos?"
        )

        self.assertEqual(
            queries[0],
            "A vitamina C reduz a duração de resfriados em adultos?",
        )
        self.assertIn("vitamina", queries[1])

    def test_returns_real_retrieval_as_unassessed_instead_of_a_verdict(self):
        pubmed = ProviderStub("PubMed")
        openalex = ProviderStub("OpenAlex", fail=True)
        runner = RetrievalPreviewRunner(
            FederatedSearchEngine((pubmed, openalex)),
            max_results_per_query=2,
        )

        result = runner.analyze(
            "A vitamina C reduz a duração de resfriados em adultos?"
        )

        self.assertEqual(result["report"]["conclusion"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("ainda não foi executada", result["report"]["summary"])
        self.assertTrue(result["articles"])
        self.assertEqual(result["articles"][0]["assessments"], [])
        self.assertGreater(result["search"]["source_failure_count"], 0)
        self.assertIsNone(
            result["verification"]["partial_verification"]["percentage"]
        )
        self.assertEqual(
            result["verification"]["partial_verification"]["total_count"],
            len(result["articles"]),
        )

    def test_optional_doi_is_searched_first(self):
        provider = ProviderStub("PubMed")
        runner = RetrievalPreviewRunner(FederatedSearchEngine((provider,)))

        result = runner.analyze(
            "Exercício físico melhora a qualidade do sono em adultos?",
            "doi:10.1000/example",
        )

        self.assertEqual(result["search"]["queries"][0], "10.1000/example")
        self.assertEqual(provider.queries[0], "10.1000/example")

    def test_analyzes_real_abstracts_without_calling_the_claim_true(self):
        class AbstractClientStub:
            def fetch_pubmed_abstract(self, pmid):
                return "Vitamin C reduced cold duration in adults."

        class AnalyzerStub:
            def analyze(self, claim, documents):
                return (
                    GeminiEvidenceAssessment(
                        pmid=documents[0].pmid,
                        relation="SUPPORTS",
                        confidence=0.8,
                        rationale="The abstract reports a compatible result.",
                        evidence_quote="Vitamin C reduced cold duration in adults.",
                        study_design="SYSTEMATIC_REVIEW_META_ANALYSIS",
                        model_name="controlled-gemini",
                    ),
                )

        runner = RetrievalPreviewRunner(
            FederatedSearchEngine((ProviderStub("PubMed"),)),
            abstract_client=AbstractClientStub(),
            evidence_analyzer=AnalyzerStub(),
        )

        result = runner.analyze(
            "A vitamina C reduz a duração de resfriados em adultos?"
        )

        self.assertEqual(
            result["report"]["conclusion"], "COMPATIBLE_WITH_EVIDENCE"
        )
        self.assertIn("preliminar", result["report"]["headline"].casefold())
        self.assertEqual(result["articles"][0]["assessments"][0]["relation"], "SUPPORTS")
        self.assertEqual(
            result["verification"]["partial_verification"]["percentage"],
            50,
        )
        self.assertEqual(
            result["verification"]["meta_analysis"]["compatibility_percentage"],
            100,
        )
        self.assertNotIn("verdadeir", str(result).casefold())


if __name__ == "__main__":
    unittest.main()
