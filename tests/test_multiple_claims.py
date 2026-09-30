import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.article_ingestion import (
    ArticleFirstAnalysisRunner,
    ArticleSubmission,
    GeminiArticleExtractor,
    ResolvedArticleDocument,
)
from fatofake.document_parsing import ParsedPage


CLAIMS = [
    {
        "text": "Hydrostatic pressure changes rhodopsin hydration.",
        "quote": "Hydrostatic pressure changed rhodopsin hydration.",
        "search_query": "hydrostatic pressure rhodopsin hydration",
    },
    {
        "text": "Hydrostatic pressure changes rhodopsin hydration!",
        "quote": "Hydrostatic pressure changed rhodopsin hydration.",
        "search_query": "rhodopsin hydration hydrostatic pressure",
    },
    {
        "text": "Osmotic pressure affects rhodopsin activation.",
        "quote": "Osmotic pressure affected rhodopsin activation.",
        "search_query": "osmotic pressure rhodopsin activation",
    },
    {
        "text": "Structural and solvent water have different roles in rhodopsin.",
        "quote": "Structural water and solvent water had distinct roles.",
        "search_query": "structural solvent water rhodopsin roles",
    },
    {
        "text": "Hydration changes alter rhodopsin conformational equilibrium.",
        "quote": "Hydration changes shifted the conformational equilibrium.",
        "search_query": "hydration rhodopsin conformational equilibrium",
    },
]


class MultiClaimGateway:
    model_name = "controlled-gemini"

    def _post_json(self, _url, _payload):
        output = {
            "title": "Water and rhodopsin",
            "doi": "10.1000/rhodopsin",
            "primary_claim": CLAIMS[0]["text"],
            "primary_claim_quote": CLAIMS[0]["quote"],
            "search_query": CLAIMS[0]["search_query"],
            "research_context": "BASIC_SCIENCE",
            "additional_claims": [item["text"] for item in CLAIMS[1:]],
            "absolute_language": [],
            "claims": CLAIMS,
        }
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(output)}]}}]}

    @staticmethod
    def _response_text(payload):
        return payload["candidates"][0]["content"]["parts"][0]["text"]


class RecordingEvidenceRunner:
    def __init__(self):
        self.calls = []

    def analyze(
        self,
        claim,
        article_reference=None,
        *,
        excluded_dois=(),
        query_override=None,
        related_seed_pmids=(),
    ):
        self.calls.append((claim, query_override, excluded_dois, related_seed_pmids))
        return {"verification": {"alerts": []}, "articles": []}


class MultipleClaimsTests(unittest.TestCase):
    def setUp(self):
        self.submission = ArticleSubmission(
            reference="https://example.org/rhodopsin",
            reference_type="url",
            file_name=None,
            mime_type=None,
            content=None,
        )
        text = " ".join(item["quote"] for item in CLAIMS)
        self.resolved = ResolvedArticleDocument(
            title="Water and rhodopsin",
            doi="10.1000/rhodopsin",
            text=text,
            pmid="12345678",
            parser_name="controlled-full-text",
            page_count=1,
            pages=(ParsedPage(6, text),),
            sections=(("Results", text),),
            content_scope="FULL_TEXT",
        )

    def test_extracts_atomic_claims_deduplicates_and_preserves_location(self):
        extracted = GeminiArticleExtractor(MultiClaimGateway()).extract(
            self.submission,
            self.resolved,
        )

        self.assertEqual(len(extracted.claims), 4)
        self.assertEqual(
            [claim.claim_id for claim in extracted.claims],
            ["claim-01", "claim-02", "claim-03", "claim-04"],
        )
        self.assertEqual(extracted.claims[0].section, "Results")
        self.assertEqual(extracted.claims[0].page, 6)
        self.assertNotEqual(extracted.claims[0].text, extracted.claims[1].text)

    def test_runs_independent_search_and_result_for_each_claim(self):
        evidence = RecordingEvidenceRunner()
        runner = ArticleFirstAnalysisRunner(
            GeminiArticleExtractor(MultiClaimGateway()),
            evidence,
        )
        runner.reference_resolver = type(
            "Resolver",
            (),
            {"resolve": lambda _self, _submission: self.resolved},
        )()

        result = runner.analyze_article(self.submission)

        self.assertEqual(len(evidence.calls), 4)
        self.assertEqual(len(result["submitted_article"]["claims"]), 4)
        self.assertEqual(len(result["claim_analyses"]), 4)
        for call, analysis in zip(evidence.calls, result["claim_analyses"]):
            self.assertEqual(call[0], analysis["claim"]["text"])
            self.assertEqual(call[1], analysis["claim"]["search_query"])
            self.assertEqual(
                analysis["result"]["user_summary"]["claim"],
                analysis["claim"]["text"],
            )


if __name__ == "__main__":
    unittest.main()
