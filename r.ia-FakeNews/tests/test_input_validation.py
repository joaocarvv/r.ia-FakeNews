import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import InputValidationError, validate_analysis_input


class ValidateAnalysisInputTests(unittest.TestCase):
    def test_accepts_claim_without_article(self) -> None:
        result = validate_analysis_input("Tomar café causa câncer.")

        self.assertEqual(result.claim, "Tomar café causa câncer.")
        self.assertIsNone(result.article_reference)
        self.assertIsNone(result.reference_type)

    def test_normalizes_claim_and_doi(self) -> None:
        result = validate_analysis_input(
            "  Vacinas   causam autismo. ",
            "https://doi.org/10.1000/xyz123",
        )

        self.assertEqual(result.claim, "Vacinas causam autismo.")
        self.assertEqual(result.article_reference, "10.1000/xyz123")
        self.assertEqual(result.reference_type, "doi")

    def test_accepts_article_url(self) -> None:
        result = validate_analysis_input(
            "Este tratamento reduz a mortalidade.",
            "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        )

        self.assertEqual(result.reference_type, "url")

    def test_rejects_empty_or_short_claim(self) -> None:
        for claim in ("", "   ", "curta"):
            with self.subTest(claim=claim):
                with self.assertRaises(InputValidationError):
                    validate_analysis_input(claim)

    def test_rejects_invalid_article_reference(self) -> None:
        with self.assertRaises(InputValidationError):
            validate_analysis_input("Alegação válida para teste.", "artigo sem identificador")


if __name__ == "__main__":
    unittest.main()
