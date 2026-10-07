import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.verification_cards import (
    build_analysis_cards,
    build_abstract_analysis_cards,
    build_unassessed_cards,
    detect_language_alerts,
    build_verification_indicators,
)


def namespace(**values):
    return SimpleNamespace(**values)


class VerificationCardsTests(unittest.TestCase):
    def test_separates_coverage_compatibility_and_methodological_confidence(self):
        result = build_verification_indicators(
            research_context="BASIC_SCIENCE",
            articles=(
                {
                    "access_level": "FULL_TEXT",
                    "publication_date": "2025",
                    "assessments": [{"relation": "SUPPORTS"}],
                    "quality": {
                        "level": "MODERATE",
                        "is_retracted": False,
                        "trial_registrations": [],
                        "datasets": [],
                    },
                    "retrieval": {
                        "sources": ["PubMed", "OpenAlex"],
                        "citation_count": 12,
                        "related_work_count": 8,
                    },
                },
            ),
        )

        self.assertEqual(set(result), {
            "search_coverage",
            "evidence_compatibility",
            "methodological_confidence",
        })
        self.assertNotIn("score", str(result).casefold())
        self.assertEqual(result["search_coverage"]["assessed_count"], 1)
        self.assertEqual(result["evidence_compatibility"]["supporting_count"], 1)
        self.assertEqual(result["methodological_confidence"]["level"], "MODERATE")
        self.assertIn(
            "Citações e ramificações não alteram",
            result["methodological_confidence"]["explanation"],
        )

    def test_retraction_is_a_critical_alert_instead_of_a_numeric_penalty(self):
        result = build_verification_indicators(
            research_context="CLINICAL",
            articles=(
                {
                    "access_level": "FULL_TEXT",
                    "assessments": [{"relation": "SUPPORTS"}],
                    "quality": {
                        "level": "HIGH",
                        "study_design": "RANDOMIZED_CLINICAL_TRIAL",
                        "is_retracted": True,
                        "trial_registrations": [{"nct_id": "NCT00000001"}],
                        "datasets": [],
                    },
                },
            ),
        )

        methodology = result["methodological_confidence"]
        self.assertEqual(methodology["level"], "CRITICAL_ALERT")
        self.assertEqual(methodology["retracted_count"], 1)
        self.assertNotIn("score", methodology)

    def test_methodological_triage_uses_risk_of_bias_and_protocol(self):
        result = build_verification_indicators(
            research_context="CLINICAL",
            articles=({
                "access_level": "FULL_TEXT",
                "assessments": [{
                    "relation": "SUPPORTS",
                    "study_row": {
                        "rob_overall": "LOW",
                        "registration_ids": ["NCT00000001"],
                    },
                }],
                "quality": {
                    "level": "NOT_ASSESSED",
                    "study_design": "RANDOMIZED_CLINICAL_TRIAL",
                    "is_retracted": False,
                    "trial_registrations": [],
                    "datasets": [],
                },
            },),
            assess_methodology=True,
        )

        methodology = result["methodological_confidence"]
        self.assertEqual(methodology["level"], "HIGH")
        self.assertEqual(methodology["registered_protocol_count"], 1)
        self.assertIn("triagem automatizada", methodology["explanation"])

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
