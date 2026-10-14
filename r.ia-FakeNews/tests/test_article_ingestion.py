import base64
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.article_ingestion import (
    ArticleFirstAnalysisRunner,
    GeminiArticleExtractor,
    ResolvedArticleDocument,
    validate_article_submission,
)
from fatofake.gemini_evidence import GeminiAnalysisError, GeminiEvidenceAnalyzer


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
            "research_context": "BASIC_SCIENCE",
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
        seed_doi=None,
        seed_authors=(),
        **_options,
    ):
        self.calls.append(
            (
                claim,
                article_reference,
                excluded_dois,
                query_override,
                related_seed_pmids,
                seed_doi,
                seed_authors,
            )
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


class ResolverStub:
    def __init__(self, resolved):
        self.resolved = resolved

    def resolve(self, _submission):
        return self.resolved


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

    def test_retries_once_when_url_context_returns_empty_candidate(self):
        class FlakyGateway(GatewayStub):
            _response_text = staticmethod(GeminiEvidenceAnalyzer._response_text)

            def _post_json(self, url, payload):
                if not self.payloads:
                    self.payloads.append(payload)
                    return {"candidates": [{"finishReason": "OTHER"}]}
                return super()._post_json(url, payload)

        gateway = FlakyGateway()
        submission = validate_article_submission({"article_reference": "10.1000/target"})

        extracted = GeminiArticleExtractor(gateway).extract(submission)

        self.assertEqual(len(gateway.payloads), 2)
        self.assertIn("reduces symptoms", extracted.primary_claim)

    def test_gives_up_after_second_empty_response(self):
        class EmptyGateway(GatewayStub):
            _response_text = staticmethod(GeminiEvidenceAnalyzer._response_text)

            def _post_json(self, _url, payload):
                self.payloads.append(payload)
                return {"candidates": [{"finishReason": "OTHER"}]}

        gateway = EmptyGateway()
        submission = validate_article_submission({"article_reference": "10.1000/target"})

        with self.assertRaises(GeminiAnalysisError):
            GeminiArticleExtractor(gateway).extract(submission)
        self.assertEqual(len(gateway.payloads), 2)

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
            result["user_summary"]["claim"],
            "The treatment reduces symptoms in adults.",
        )
        self.assertNotIn("confidence_index", result["verification"])
        self.assertEqual(
            set(result["verification"]["indicators"]),
            {
                "search_coverage",
                "evidence_compatibility",
                "methodological_confidence",
            },
        )
        self.assertEqual(
            result["verification"]["alerts"][0]["code"],
            "ABSOLUTE_LANGUAGE_IN_ARTICLE",
        )
        self.assertEqual(
            result["article_dossier"]["methodology"]["classification_source"],
            "UNRESOLVED",
        )
        self.assertEqual(
            result["article_dossier"]["identity"]["status"],
            "UNKNOWN",
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

    def test_submitted_retraction_becomes_critical_alert(self):
        identity = SimpleNamespace(
            status="VERIFIED",
            reason="DOI e título compatíveis.",
            crossref_url="https://doi.org/10.1000/target",
            crossref_authors=(),
            crossref_work_type="journal-article",
            crossref_updates=(SimpleNamespace(update_type="retraction"),),
        )
        resolved = ResolvedArticleDocument(
            title="Controlled article",
            doi="10.1000/target",
            text="Controlled scientific article with enough text for extraction.",
            pmid="12345678",
            content_scope="FULL_TEXT",
            identity_verification=identity,
        )
        runner = ArticleFirstAnalysisRunner(
            GeminiArticleExtractor(GatewayStub()),
            EvidenceRunnerStub(),
            reference_resolver=ResolverStub(resolved),
        )
        submission = validate_article_submission(
            {"article_reference": "https://pubmed.ncbi.nlm.nih.gov/12345678/"}
        )

        result = runner.analyze_article(submission)

        self.assertEqual(
            result["verification"]["alerts"][0]["code"],
            "SUBMITTED_ARTICLE_RETRACTED",
        )
        self.assertEqual(
            result["article_dossier"]["editorial_status"]["retraction"],
            "RETRACTED",
        )


if __name__ == "__main__":
    unittest.main()
