import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.article_ingestion import ArticleSubmission, ResolvedArticleDocument
from fatofake.document_parsing import ParsedPage
from fatofake.whole_article_analysis import GeminiWholeArticleAnalyzer, detect_tables_and_figures


class GatewayStub:
    model_name = "controlled-model"

    def __init__(self, output):
        self.output = output
        self.payloads = []

    def _post_json(self, _url, payload):
        self.payloads.append(payload)
        return {
            "candidates": [{"content": {"parts": [{"text": json.dumps(self.output)}]}}]
        }

    @staticmethod
    def _response_text(payload):
        return payload["candidates"][0]["content"]["parts"][0]["text"]


class SequencedGateway(GatewayStub):
    def __init__(self, outputs):
        super().__init__(None)
        self.outputs = list(outputs)

    def _post_json(self, _url, payload):
        self.payloads.append(payload)
        output = self.outputs.pop(0)
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(output)}]}}]}


def report_output():
    citation = {"quote": "The intervention reduced symptoms by 18 percent.", "section": "Results"}
    return {
        "overview": {
            "purpose": "Evaluate an intervention.",
            "research_question": "Does it reduce symptoms?",
            "source_language": "Português",
            "plain_language_summary": "Symptoms were reduced in the studied sample.",
            "plain_language_summary_original": "Symptoms were reduced in the studied sample.",
            "authors_conclusion": "The intervention may help.",
        },
        "study": {
            "design": "Randomized trial",
            "population": "Adults",
            "sample_size": "120",
            "intervention_or_exposure": "Treatment",
            "comparator": "Placebo",
            "outcomes": ["Symptoms"],
            "follow_up": "12 weeks",
            "statistical_methods": ["Regression"],
        },
        "section_summaries": [
            {"section": "Methods", "summary": "Controlled design.", "key_points": ["Randomized"], "citations": []},
            {"section": "Results", "summary": "Symptoms improved.", "key_points": ["18 percent"], "citations": [citation]},
        ],
        "main_findings": [
            {"finding": "Symptoms improved.", "numbers": "18 percent", "interpretation": "Benefit in this sample.", "citations": [citation]}
        ],
        "strengths": ["Controlled comparator"],
        "limitations": ["Short follow-up"],
        "internal_consistency": {"status": "CONSISTENT", "explanation": "Results support the conclusion.", "citations": [citation]},
        "red_flags": [],
        "glossary": [{"term": "Regression", "definition": "A statistical method."}],
    }


class WholeArticleAnalysisTests(unittest.TestCase):
    def test_builds_full_document_dossier_and_verifies_citations(self):
        gateway = GatewayStub(report_output())
        resolved = ResolvedArticleDocument(
            title="Controlled study",
            doi="10.1000/test",
            text=(
                "## Methods\nParticipants were randomized.\n\n"
                "## Results\nThe intervention reduced symptoms by 18 percent."
            ),
            parser_name="liteparse",
            page_count=2,
            pages=(
                ParsedPage(1, "Participants were randomized."),
                ParsedPage(2, "The intervention reduced symptoms by 18 percent."),
            ),
            sections=(
                ("Methods", "Participants were randomized."),
                ("Results", "The intervention reduced symptoms by 18 percent."),
            ),
            content_scope="LOCAL_PDF_FULL_TEXT",
        )
        submission = ArticleSubmission(None, None, "study.pdf", "application/pdf", b"pdf")

        report = GeminiWholeArticleAnalyzer(gateway).analyze(submission, resolved)

        self.assertTrue(report["coverage"]["full_article_available"])
        self.assertEqual(report["coverage"]["section_coverage_percentage"], 100)
        citation = report["main_findings"][0]["citations"][0]
        self.assertTrue(citation["verified"])
        self.assertEqual(citation["page"], 2)
        sent_text = gateway.payloads[0]["contents"][0]["parts"][1]["text"]
        self.assertIn("Participants were randomized", sent_text)
        self.assertIn("reduced symptoms", sent_text)

    def test_marks_url_context_as_unverified_partial_reading(self):
        gateway = GatewayStub(report_output())
        submission = ArticleSubmission("10.1000/test", "doi", None, None, None)

        report = GeminiWholeArticleAnalyzer(gateway).analyze(submission, None)

        self.assertFalse(report["coverage"]["full_article_available"])
        self.assertFalse(report["coverage"]["citation_verification_available"])
        self.assertFalse(report["main_findings"][0]["citations"][0]["verified"])
        self.assertEqual(gateway.payloads[0]["tools"], [{"url_context": {}}])

    def test_foreign_summary_is_translated_and_original_is_preserved(self):
        spanish = report_output()
        spanish["overview"].update({
            "source_language": "Espanhol",
            "purpose": "Describir los resultados clínicos.",
            "research_question": "¿Cuáles son los resultados clínicos?",
            "plain_language_summary": "Los síntomas disminuyeron en la muestra estudiada.",
            "plain_language_summary_original": "Los síntomas disminuyeron en la muestra estudiada.",
        })
        paths = GeminiWholeArticleAnalyzer._narrative_paths(spanish)
        translated = [value for _path, value in paths]
        replacements = {
            ("overview", "purpose"): "Descrever os resultados clínicos.",
            ("overview", "research_question"): "Quais são os resultados clínicos?",
            ("overview", "plain_language_summary"): "Os sintomas diminuíram na amostra estudada.",
        }
        translated = [replacements.get(path, value) for (path, _value), value in zip(paths, translated)]
        gateway = SequencedGateway([
            spanish,
            {"items": [{"index": index, "translated_text": value} for index, value in enumerate(translated)]},
        ])
        resolved = ResolvedArticleDocument(
            title="Estudio controlado",
            doi="10.1000/es",
            text="Los síntomas disminuyeron en la muestra estudiada.",
            parser_name="liteparse",
            page_count=1,
            pages=(ParsedPage(1, "Los síntomas disminuyeron en la muestra estudiada."),),
            sections=(("Resultados", "Los síntomas disminuyeron en la muestra estudiada."),),
            content_scope="LOCAL_PDF_FULL_TEXT",
        )
        report = GeminiWholeArticleAnalyzer(gateway).analyze(
            ArticleSubmission(None, None, "estudio.pdf", "application/pdf", b"pdf"),
            resolved,
        )
        overview = report["overview"]
        self.assertEqual(overview["purpose"], "Descrever os resultados clínicos.")
        self.assertEqual(overview["research_question"], "Quais são os resultados clínicos?")
        self.assertEqual(overview["plain_language_summary"], "Os sintomas diminuíram na amostra estudada.")
        self.assertEqual(overview["plain_language_summary_original"], "Los síntomas disminuyeron en la muestra estudiada.")
        self.assertEqual(overview["translation_status"], "TRANSLATED")
        self.assertTrue(report["original_narrative"])
        self.assertIn("português brasileiro", gateway.payloads[1]["contents"][0]["parts"][0]["text"])

    def test_spanish_table_caption_is_mapped_to_source_page(self):
        resolved = ResolvedArticleDocument(
            title="Estudio",
            doi=None,
            text="Tabla 1 — Características de la población",
            pages=(ParsedPage(3, "Tabla 1 — Características de la población"),),
            content_scope="LOCAL_PDF_FULL_TEXT",
        )
        detected = detect_tables_and_figures(resolved)
        report = {"tables_figures": [{"label": "Tabla 1", "kind": "TABLE"}]}
        GeminiWholeArticleAnalyzer._attach_table_figure_pages(
            report, {"detected_tables_figures": detected}
        )
        self.assertEqual(report["tables_figures"][0]["page"], 3)


if __name__ == "__main__":
    unittest.main()
