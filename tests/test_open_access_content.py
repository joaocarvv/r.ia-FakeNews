import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.document_parsing import ParsedDocument, ParsedPage
from fatofake.open_access_content import HttpDocument, OpenAccessContentClient


class ParserStub:
    def parse_pdf(self, body):
        self.body = body
        pages = (
            ParsedPage(5, "# Methods\nParticipants were randomly assigned."),
            ParsedPage(6, "# Results\nThe intervention reduced symptoms by 18 percent."),
        )
        return ParsedDocument(
            text="\n\n".join(page.text for page in pages),
            page_count=2,
            parser_name="liteparse",
            used_ocr=False,
            pages=pages,
        )


class OpenAccessContentTests(unittest.TestCase):
    def test_preserves_pdf_page_numbers(self):
        parser = ParserStub()
        client = OpenAccessContentClient(
            parser,
            fetch_document=lambda _url: HttpDocument(
                "https://publisher.test/article.pdf", "application/pdf", b"%PDF-test"
            ),
        )

        content = client.retrieve(
            pmid="123",
            doi="10.1000/test",
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/123/",
            full_text_url="https://publisher.test/article.pdf",
            abstract="Controlled abstract.",
        )

        self.assertEqual(content.access_level, "OPEN_ACCESS_FULL_TEXT")
        self.assertEqual(content.sections[1].page_number, 6)
        self.assertIn("Results", content.sections[1].text)
        self.assertEqual(parser.body, b"%PDF-test")

    def test_extracts_structured_html_sections_without_inventing_pages(self):
        paragraph = (
            "Participants receiving the intervention reported fewer symptoms and "
            "the confidence interval excluded the null value. " * 6
        )
        html = (
            "<html><body><article><h2>Results</h2><p>"
            + paragraph
            + "</p><h2>Conclusion</h2><p>"
            + paragraph
            + "</p></article></body></html>"
        ).encode()
        client = OpenAccessContentClient(
            ParserStub(),
            fetch_document=lambda _url: HttpDocument(
                "https://publisher.test/article", "text/html", html
            ),
        )

        content = client.retrieve(
            pmid="123",
            doi=None,
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/123/",
            full_text_url="https://publisher.test/article",
            abstract=None,
        )

        self.assertEqual([section.title for section in content.sections], ["Results", "Conclusion"])
        self.assertTrue(all(section.page_number is None for section in content.sections))


if __name__ == "__main__":
    unittest.main()
