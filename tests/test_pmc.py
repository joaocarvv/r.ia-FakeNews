import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import PmcClient, Publication, retrieve_article_content


PUBMED_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <Abstract>
          <AbstractText Label="OBJECTIVE">Evaluate coffee consumption.</AbstractText>
          <AbstractText Label="RESULTS">An association was observed.</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""

PMC_XML = b"""<?xml version="1.0"?>
<pmc-articleset>
  <article>
    <body>
      <sec>
        <title>Introduction</title>
        <p>Coffee is widely consumed.</p>
      </sec>
      <sec>
        <title>Methods</title>
        <p>We searched scientific databases.</p>
        <sec><title>Analysis</title><p>We pooled the estimates.</p></sec>
      </sec>
    </body>
  </article>
</pmc-articleset>
"""


class QueueJsonFetcher:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)

    def __call__(self, url: str, params: dict[str, str]) -> dict:
        return self.responses.pop(0)


class QueueXmlFetcher:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, params: dict[str, str]) -> bytes:
        self.calls.append((url, dict(params)))
        return self.responses.pop(0)


def publication() -> Publication:
    return Publication(
        pmid="33431520",
        title="Coffee consumption and risk of prostate cancer.",
        authors=("Chen X",),
        journal="BMJ open",
        publication_date="2021 Jan 11",
        doi="10.1136/bmjopen-2020-038902",
        url="https://pubmed.ncbi.nlm.nih.gov/33431520/",
        matched_queries=("33431520[pmid]",),
    )


class PmcTests(unittest.TestCase):
    def test_retrieves_abstract_and_full_text(self) -> None:
        client = PmcClient(
            fetch_json=QueueJsonFetcher([{"records": [{"pmcid": "PMC7805365"}]}]),
            fetch_xml=QueueXmlFetcher([PUBMED_XML, PMC_XML]),
        )

        content = retrieve_article_content(publication(), client)

        self.assertEqual(content.pmcid, "PMC7805365")
        self.assertEqual(content.access_level, "FULL_TEXT")
        self.assertIn("OBJECTIVE: Evaluate coffee consumption.", content.abstract or "")
        self.assertIn("Coffee is widely consumed.", content.full_text or "")
        self.assertEqual([section.title for section in content.sections], [
            "Introduction",
            "Methods",
        ])
        self.assertIn("We pooled the estimates.", content.sections[1].text)

    def test_returns_abstract_only_when_article_is_not_in_pmc(self) -> None:
        xml_fetcher = QueueXmlFetcher([PUBMED_XML])
        client = PmcClient(
            fetch_json=QueueJsonFetcher([{"records": [{"pmid": "33431520"}]}]),
            fetch_xml=xml_fetcher,
        )

        content = retrieve_article_content(publication(), client)

        self.assertEqual(content.access_level, "ABSTRACT_ONLY")
        self.assertIsNone(content.pmcid)
        self.assertIsNone(content.full_text)
        self.assertEqual(len(xml_fetcher.calls), 1)

    def test_handles_pubmed_record_without_abstract(self) -> None:
        client = PmcClient(
            fetch_json=QueueJsonFetcher([{"records": []}]),
            fetch_xml=QueueXmlFetcher([b"<PubmedArticleSet />"]),
        )

        content = retrieve_article_content(publication(), client)

        self.assertIsNone(content.abstract)
        self.assertEqual(content.access_level, "ABSTRACT_ONLY")


if __name__ == "__main__":
    unittest.main()
