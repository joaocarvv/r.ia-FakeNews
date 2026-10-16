import json
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.gemini_evidence import (
    EvidenceDocument,
    GeminiAnalysisError,
    GeminiEvidenceAnalyzer,
)


def response_with(payload):
    return {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(payload)}]}}
        ]
    }


class GeminiEvidenceTests(unittest.TestCase):
    def document(self):
        return EvidenceDocument(
            pmid="123",
            title="Vitamin C and colds",
            abstract="Vitamin C reduced cold duration by eight percent in adults.",
            source_url="https://pubmed.ncbi.nlm.nih.gov/123/",
        )

    def test_requests_structured_json_and_preserves_grounded_quote(self):
        calls = []

        def post(url, payload):
            calls.append((url, payload))
            return response_with(
                {
                    "assessments": [
                        {
                            "pmid": "123",
                            "relation": "SUPPORTS",
                            "confidence": 0.82,
                            "rationale": "The result addresses the claim.",
                            "evidence_quote": "Vitamin C reduced cold duration by eight percent in adults.",
                            "study_design": "RANDOMIZED_CLINICAL_TRIAL",
                        }
                    ]
                }
            )

        analyzer = GeminiEvidenceAnalyzer("secret", post_json=post)
        result = analyzer.analyze("Vitamin C reduces cold duration.", [self.document()])

        self.assertEqual(result[0].relation, "SUPPORTS")
        self.assertEqual(result[0].confidence, 0.82)
        self.assertIn(":generateContent", calls[0][0])
        config = calls[0][1]["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["temperature"], 0)
        self.assertIn("responseSchema", config)

    def test_invalidates_a_quote_not_present_in_the_source(self):
        def post(_url, _payload):
            return response_with(
                {
                    "assessments": [
                        {
                            "pmid": "123",
                            "relation": "SUPPORTS",
                            "confidence": 0.99,
                            "rationale": "Unsupported generated rationale.",
                            "evidence_quote": "A fabricated sentence.",
                            "study_design": "RANDOMIZED_CLINICAL_TRIAL",
                        }
                    ]
                }
            )

        result = GeminiEvidenceAnalyzer("secret", post_json=post).analyze(
            "Vitamin C reduces cold duration.", [self.document()]
        )

        self.assertEqual(result[0].relation, "UNCERTAIN")
        self.assertEqual(result[0].confidence, 0.0)
        self.assertIsNone(result[0].evidence_quote)
        self.assertIn("não foi localizado", result[0].rationale)

    def test_ignores_unknown_or_duplicate_pmids(self):
        def post(_url, _payload):
            assessment = {
                "relation": "NEUTRAL",
                "confidence": 0.7,
                "rationale": "No direct result.",
                "evidence_quote": "",
                "study_design": "UNKNOWN",
            }
            return response_with(
                {
                    "assessments": [
                        {"pmid": "999", **assessment},
                        {"pmid": "123", **assessment},
                        {"pmid": "123", **assessment},
                    ]
                }
            )

        result = GeminiEvidenceAnalyzer("secret", post_json=post).analyze(
            "Vitamin C reduces cold duration.", [self.document()]
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].pmid, "123")

    def test_retries_transient_503_and_then_succeeds(self):
        headers = Message()
        waits = []
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b'{"ok": true}'
        with patch(
            "fatofake.gemini_evidence.urlopen",
            side_effect=[
                HTTPError("https://example.test", 503, "Unavailable", headers, None),
                response,
            ],
        ) as request:
            analyzer = GeminiEvidenceAnalyzer(
                "secret", max_attempts=3, retry_backoff=0.25, sleep=waits.append
            )
            result = analyzer._request_json("https://example.test", {"x": 1})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(waits, [0.25])

    def test_reports_temporary_unavailability_after_retry_limit(self):
        headers = Message()
        error = HTTPError("https://example.test", 503, "Unavailable", headers, None)
        with patch("fatofake.gemini_evidence.urlopen", side_effect=error):
            analyzer = GeminiEvidenceAnalyzer(
                "secret", max_attempts=2, retry_backoff=0, sleep=lambda _delay: None
            )
            with self.assertRaisesRegex(
                GeminiAnalysisError, "temporariamente indisponível após 2 tentativas"
            ):
                analyzer._request_json("https://example.test", {"x": 1})


if __name__ == "__main__":
    unittest.main()
