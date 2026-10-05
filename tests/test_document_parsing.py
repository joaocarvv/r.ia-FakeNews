import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.document_parsing import DocumentParsingError, LiteParseDocumentParser


class ResultStub:
    text = "# Study\n\n" + ("Scientific result with traceable content. " * 4)
    total_pages = 3
    pages = (
        type("Page", (), {"page_num": 1, "markdown": "# Introduction\nBackground text."})(),
        type("Page", (), {"page_num": 2, "markdown": "# Results\nScientific result."})(),
    )


class ParserStub:
    def __init__(self, **options):
        self.options = options
        self.closed = False

    def parse(self, content):
        self.content = content
        return ResultStub()

    def close(self):
        self.closed = True


class LiteParseDocumentParserTests(unittest.TestCase):
    def test_converts_pdf_bytes_to_markdown_with_provenance(self):
        created = []

        def factory(**options):
            parser = ParserStub(**options)
            created.append(parser)
            return parser

        parsed = LiteParseDocumentParser(parser_factory=factory).parse_pdf(b"%PDF-test")

        self.assertEqual(parsed.parser_name, "liteparse")
        self.assertEqual(parsed.page_count, 3)
        self.assertEqual(parsed.pages[1].page_number, 2)
        self.assertIn("Results", parsed.pages[1].text)
        self.assertIn("Scientific result", parsed.text)
        self.assertEqual(created[0].content, b"%PDF-test")
        self.assertEqual(created[0].options["output_format"], "markdown")
        self.assertTrue(created[0].closed)

    def test_rejects_documents_without_enough_text(self):
        class EmptyParser(ParserStub):
            def parse(self, _content):
                result = ResultStub()
                result.text = "too short"
                return result

        with self.assertRaisesRegex(DocumentParsingError, "texto suficiente"):
            LiteParseDocumentParser(parser_factory=EmptyParser).parse_pdf(b"%PDF-test")


if __name__ == "__main__":
    unittest.main()
