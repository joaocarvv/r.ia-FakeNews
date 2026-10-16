import base64
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.article_ingestion import (
    ArticleFirstAnalysisRunner,
    GeminiArticleExtractor,
    validate_article_submission,
)


class GatewayStub:
    model_name = "controlled-gemini"

    def __init__(self):
        self.payloads = []

    def _post_json(self, _url, payload):
        self.payloads.append(payload)
        output = {
            "title": "Controlled article",
            "doi": "10.1000/target",
            "primary_claim": "The treatment reduces symptoms in adults.",
            "search_query": "treatment symptoms adults",
            "additional_claims": [],
            "absolute_language": ["completely eliminates symptoms"],
        }
        return {
            "candidates": [
                {"content": {"parts": [{"text": json.dumps(output)}]}}
            ]
        }

    @staticmethod
    def _response_text(payload):
        return payload["candidates"][0]["content"]["parts"][0]["text"]


class EvidenceRunnerStub:
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
        self.calls.append(
            (claim, article_reference, excluded_dois, query_override, related_seed_pmids)
        )
        return {"verification": {"alerts": []}, "articles": []}


class ParsedDocumentStub:
    text = "Parsed scientific article with enough text for claim extraction."
    page_count = 4
    parser_name = "liteparse"


class DocumentParserStub:
    def __init__(self):
        self.contents = []

    def parse_pdf(self, content):
        self.contents.append(content)
        return ParsedDocumentStub()


class ArticleIngestionTests(unittest.TestCase):
    def test_validates_pdf_file(self):
        raw = b"%PDF-controlled"
        submission = validate_article_submission(
            {
                "article_file": {
                    "name": "study.pdf",
                    "mime_type": "application/pdf",
                    "data_base64": base64.b64encode(raw).decode("ascii"),
                }
            }
        )

        self.assertEqual(submission.content, raw)
        self.assertEqual(submission.mime_type, "application/pdf")

    def test_extracts_claim_from_image_and_sends_inline_data(self):
        gateway = GatewayStub()
        submission = validate_article_submission(
            {
                "article_file": {
                    "name": "article.png",
                    "mime_type": "image/png",
                    "data_base64": base64.b64encode(b"png-bytes").decode("ascii"),
                }
            }
        )

        extracted = GeminiArticleExtractor(gateway).extract(submission)

        self.assertIn("reduces symptoms", extracted.primary_claim)
        parts = gateway.payloads[0]["contents"][0]["parts"]
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/png")

    def test_article_runner_excludes_submitted_doi_from_evidence(self):
        evidence = EvidenceRunnerStub()
        runner = ArticleFirstAnalysisRunner(
            GeminiArticleExtractor(GatewayStub()), evidence
        )
        submission = validate_article_submission(
            {"article_reference": "https://doi.org/10.1000/target"}
        )

        result = runner.analyze_article(submission)

        self.assertEqual(evidence.calls[0][2], ("10.1000/target",))
        self.assertEqual(evidence.calls[0][3], "treatment symptoms adults")
        self.assertEqual(
            result["submitted_article"]["primary_claim"],
            "The treatment reduces symptoms in adults.",
        )
        self.assertEqual(
            result["verification"]["alerts"][0]["code"],
            "ABSOLUTE_LANGUAGE_IN_ARTICLE",
        )
        self.assertFalse(
            any(
                item["code"] == "NO_ARTICLE_SUBMITTED"
                for item in result["verification"]["alerts"]
            )
        )

    def test_article_runner_parses_pdf_locally_before_gemini(self):
        gateway = GatewayStub()
        parser = DocumentParserStub()
        runner = ArticleFirstAnalysisRunner(
            GeminiArticleExtractor(gateway), EvidenceRunnerStub(), document_parser=parser
        )
        submission = validate_article_submission(
            {
                "article_file": {
                    "name": "study.pdf",
                    "mime_type": "application/pdf",
                    "data_base64": base64.b64encode(b"%PDF-controlled").decode("ascii"),
                }
            }
        )

        result = runner.analyze_article(submission)

        self.assertEqual(parser.contents, [b"%PDF-controlled"])
        parts = gateway.payloads[0]["contents"][0]["parts"]
        self.assertIn("CONTEÚDO RECUPERADO", parts[1]["text"])
        self.assertNotIn("inlineData", parts[1])
        self.assertEqual(result["submitted_article"]["document_parser"], "liteparse")
        self.assertEqual(result["submitted_article"]["page_count"], 4)


if __name__ == "__main__":
    unittest.main()
