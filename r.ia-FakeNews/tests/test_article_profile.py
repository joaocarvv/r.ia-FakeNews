import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.article_profile import build_article_dossier
from fatofake.quality_validation import StudyDesign, classify_study_design


class ArticleProfileTests(unittest.TestCase):
    def test_pubmed_publication_type_has_priority_over_model_fallback(self):
        result = classify_study_design(
            "A clinical investigation",
            "The methods are not explicit in this abstract.",
            publication_types=("Journal Article", "Randomized Controlled Trial"),
            llm_context="SYSTEMATIC_REVIEW",
        )

        self.assertEqual(result.design, StudyDesign.RANDOMIZED_CLINICAL_TRIAL)
        self.assertEqual(result.source, "PUBMED_PUBLICATION_TYPE")

    def test_model_is_used_only_when_deterministic_signals_do_not_resolve(self):
        result = classify_study_design(
            "Molecular hydration of rhodopsin",
            "Spectroscopy was used to examine conformational states.",
            llm_context="BASIC_SCIENCE",
        )

        self.assertEqual(result.design, StudyDesign.OTHER)
        self.assertEqual(result.source, "GEMINI_FALLBACK")

    def test_systematic_review_is_not_automatically_called_meta_analysis(self):
        result = classify_study_design(
            "A systematic review of rehabilitation interventions",
            "We synthesized the available studies without statistical pooling.",
            publication_types=("Systematic Review",),
            llm_context="SYSTEMATIC_REVIEW",
        )

        self.assertEqual(result.design, StudyDesign.SYSTEMATIC_REVIEW)
        self.assertEqual(result.source, "PUBMED_PUBLICATION_TYPE")

    def test_builds_dossier_and_keeps_unverified_fields_explicit(self):
        identity = SimpleNamespace(
            status="VERIFIED",
            reason="DOI e título compatíveis.",
            crossref_url="https://doi.org/10.1000/example",
            crossref_authors=("Ana Silva", "Bruno Souza"),
            crossref_work_type="journal-article",
            crossref_updates=(),
        )
        text = (
            "Methods: We enrolled 240 participants under protocol NCT12345678. "
            "Results: symptoms were reduced."
        )
        sections = (
            ("Funding", "Supported by the Example Foundation."),
            ("Competing interests", "The authors declare no competing interests."),
            ("Data availability", "Data are available in a public repository."),
        )

        dossier = build_article_dossier(
            title="Controlled trial",
            doi="10.1000/example",
            pmid="12345678",
            authors=("Silva A", "Souza B"),
            journal="Example Journal",
            publication_date="2025",
            publication_types=("Randomized Controlled Trial",),
            text=text,
            sections=sections,
            identity=identity,
            llm_context="SYSTEMATIC_REVIEW",
            absolute_language=("always works",),
        )

        self.assertEqual(dossier["structured_fields"]["publication_types"]["value"], ["Randomized Controlled Trial"])
        self.assertEqual(dossier["structured_fields"]["publication_types"]["field"], "pubtype")
        self.assertEqual(dossier["identity"]["doi_and_title_consistency"], "CONFIRMED")
        self.assertEqual(dossier["identity"]["authors_consistency"], "CONSISTENT")
        self.assertEqual(
            dossier["methodology"]["study_design"],
            "RANDOMIZED_CLINICAL_TRIAL",
        )
        self.assertEqual(
            dossier["methodology"]["classification_source"],
            "PUBMED_PUBLICATION_TYPE",
        )
        self.assertIsNone(dossier["methodology"]["sample_size"]["value"])
        self.assertEqual(dossier["methodology"]["sample_mentions"][0]["value"], 240)
        self.assertEqual(
            dossier["methodology"]["protocol"]["identifiers"],
            ["NCT12345678"],
        )
        self.assertEqual(dossier["transparency"]["funding"]["status"], "FOUND")
        self.assertEqual(dossier["editorial_status"]["peer_review"], "UNKNOWN")
        self.assertEqual(
            dossier["results_conclusion_consistency"]["status"],
            "NOT_EVALUATED",
        )


    def test_text_and_model_cannot_confirm_design_in_dossier(self):
        dossier = build_article_dossier(
            title="Randomized trial", doi=None, pmid=None,
            text="Protocol NCT12345678 was mentioned. A sample of 240 adults.",
            llm_context="RANDOMIZED_CLINICAL_TRIAL",
        )
        self.assertEqual(dossier["methodology"]["study_design"], "UNKNOWN")
        self.assertEqual(dossier["structured_fields"], {})
        self.assertIsNone(dossier["methodology"]["sample_size"]["value"])


    def test_retraction_metadata_generates_explicit_status(self):
        identity = SimpleNamespace(
            status="VERIFIED",
            reason="verified",
            crossref_url="https://doi.org/10.1000/example",
            crossref_authors=(),
            crossref_work_type="journal-article",
            crossref_updates=(SimpleNamespace(update_type="retraction"),),
        )

        dossier = build_article_dossier(
            title="Retracted article",
            doi="10.1000/example",
            pmid="12345678",
            identity=identity,
        )

        self.assertEqual(dossier["editorial_status"]["retraction"], "RETRACTED")


if __name__ == "__main__":
    unittest.main()
