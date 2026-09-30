import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.result_presentation import build_user_summary


def article(pmid, relation, *, access="FULL_TEXT", page=None):
    return {
        "pmid": pmid,
        "title": f"Study {pmid}",
        "publication_date": "2025",
        "url": f"https://example.org/{pmid}",
        "access_level": access,
        "quality": {"study_design": "OBSERVATIONAL"},
        "assessments": [{
            "relation": relation,
            "confidence": 0.8,
            "evidence": {
                "text": f"Traceable result for {pmid}.",
                "section": "Results",
                "page": page,
                "content_scope": access,
                "source_url": f"https://example.org/{pmid}",
            },
        }],
    }


class ResultPresentationTests(unittest.TestCase):
    def test_builds_one_coherent_summary_with_explicit_denominators(self):
        result = {
            "submitted_article": {
                "primary_claim": "The intervention reduces symptoms.",
                "content_scope": "ABSTRACT_ONLY",
            },
            "articles": (
                article("1", "SUPPORTS", page=6),
                article("2", "NEUTRAL", access="ABSTRACT_ONLY"),
            ),
        }

        summary = build_user_summary(result)

        self.assertEqual(summary["status"], "PREDOMINANTLY_COMPATIBLE")
        self.assertIn("2 artigos", summary["summary"])
        self.assertIn("2 tiveram trechos", summary["summary"])
        self.assertEqual(summary["evidence_balance"]["SUPPORTS"], 1)
        self.assertEqual(summary["reading"]["full_text_count"], 1)
        self.assertEqual(summary["reading"]["abstract_only_count"], 1)
        self.assertEqual(summary["findings"][0]["location"], "Seção Results, página 6")
        self.assertIn("Envie o PDF", summary["next_action"])
        self.assertTrue(any("somente o abstract" in item for item in summary["caveats"]))

    def test_calls_conflicting_directions_divergent_without_a_truth_verdict(self):
        summary = build_user_summary({
            "input": {"claim": "Controlled claim"},
            "articles": (article("1", "SUPPORTS"), article("2", "CONTRADICTS")),
        })

        self.assertEqual(summary["status"], "MIXED")
        self.assertIn("divergentes", summary["headline"])
        self.assertNotIn("verdadeiro", str(summary).casefold())
        self.assertNotIn("falso", str(summary).casefold())

    def test_abstains_when_no_article_has_a_comparable_passage(self):
        summary = build_user_summary({
            "input": {"claim": "Controlled claim"},
            "articles": ({
                "pmid": "1", "title": "Metadata only", "access_level": "METADATA_ONLY",
                "assessments": [],
            },),
        })

        self.assertEqual(summary["status"], "NO_DIRECT_COMPARISON")
        self.assertEqual(summary["reading"]["assessed_count"], 0)
        self.assertEqual(summary["findings"], [])
        self.assertIn("não tiveram trecho comparável", " ".join(summary["caveats"]))


if __name__ == "__main__":
    unittest.main()
