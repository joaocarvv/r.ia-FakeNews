import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.verification_cards import (
    build_abstract_analysis_cards,
    build_analysis_cards,
    build_unassessed_cards,
    build_verification_confidence,
    detect_language_alerts,
)


def namespace(**values):
    return SimpleNamespace(**values)


class VerificationCardsTests(unittest.TestCase):
    def test_confidence_index_measures_coverage_not_truth(self):
        result = build_verification_confidence(
            research_context="BASIC_SCIENCE",
            articles=(
                {
                    "publication_date": "2025",
                    "assessments": [{"relation": "SUPPORTS"}],
                    "retrieval": {
                        "sources": ["PubMed", "OpenAlex"],
                        "citation_count": 12,
                        "related_work_count": 8,
                    },
                },
            ),
        )

        self.assertGreater(result["score"], 0)
        self.assertIn("Não é a probabilidade", result["explanation"])
        self.assertEqual(result["components"][-1]["status"], "NOT_APPLICABLE")
    def test_unassessed_retrieval_never_invents_a_percentage(self):
        result = build_unassessed_cards(
            claim="A vitamina C reduz resfriados?",
            article_reference=None,
            retrieved_article_count=7,
        )

        self.assertIsNone(result["partial_verification"]["percentage"])
        self.assertIsNone(
            result["meta_analysis"]["compatibility_percentage"]
        )
        self.assertIsNone(
            result["clinical_trials"]["registration_percentage"]
        )
        self.assertIn("7 artigo", result["partial_verification"]["explanation"])

    def test_detects_absolute_language_without_calling_it_false(self):
        alerts = detect_language_alerts("Este tratamento sempre cura a doença.")

        self.assertEqual(alerts[0]["code"], "ABSOLUTE_LANGUAGE")
        self.assertNotIn("falso", alerts[0]["detail"].casefold())

    def test_builds_percentages_with_explicit_denominators(self):
        meta_quality = namespace(
            study_design=namespace(value="SYSTEMATIC_REVIEW_META_ANALYSIS"),
            trial_registrations=(),
            is_retracted=False,
        )
        trial_quality = namespace(
            study_design=namespace(value="RANDOMIZED_CLINICAL_TRIAL"),
            trial_registrations=(namespace(has_results=True),),
            is_retracted=False,
        )
        articles = (
            namespace(
                publication=namespace(pmid="1", url="https://example.org/1"),
                quality_report=meta_quality,
            ),
            namespace(
                publication=namespace(pmid="2", url="https://example.org/2"),
                quality_report=trial_quality,
            ),
        )
        analysis = namespace(
            articles=articles,
            failures=(namespace(stage="content_retrieval"),),
            analysis_input=namespace(
                claim="O tratamento reduz sintomas.",
                article_reference="10.1000/example",
            ),
            synthesis=namespace(
                articles=(
                    namespace(
                        pmid="1",
                        direction=namespace(value="SUPPORTS"),
                        uncertain_count=0,
                        assessment_count=1,
                    ),
                    namespace(
                        pmid="2",
                        direction=namespace(value="CONTRADICTS"),
                        uncertain_count=0,
                        assessment_count=1,
                    ),
                )
            ),
        )

        result = build_analysis_cards(analysis)

        self.assertEqual(result["partial_verification"]["percentage"], 67)
        self.assertEqual(result["partial_verification"]["verified_count"], 2)
        self.assertEqual(
            result["meta_analysis"]["compatibility_percentage"], 100
        )
        self.assertEqual(
            result["clinical_trials"]["registration_percentage"], 100
        )
        self.assertEqual(result["clinical_trials"]["with_results_count"], 1)
        self.assertTrue(
            any(item["code"] == "PROCESSING_FAILURES" for item in result["alerts"])
        )

    def test_abstract_cards_do_not_claim_trial_registration_was_checked(self):
        result = build_abstract_analysis_cards(
            claim="O tratamento reduz sintomas.",
            article_reference=None,
            retrieved_article_count=4,
            assessments=(
                namespace(
                    study_design="RANDOMIZED_CLINICAL_TRIAL",
                    relation="SUPPORTS",
                ),
                namespace(
                    study_design="UNKNOWN",
                    relation="UNCERTAIN",
                ),
            ),
        )

        self.assertEqual(result["partial_verification"]["percentage"], 50)
        self.assertEqual(result["clinical_trials"]["eligible_count"], 1)
        self.assertIsNone(result["clinical_trials"]["registration_percentage"])
        self.assertEqual(result["clinical_trials"]["status"], "NOT_EVALUATED")


if __name__ == "__main__":
    unittest.main()
