import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    CrossrefClient,
    CrossrefNotFoundError,
    Publication,
    verify_publication_identity,
)


CROSSREF_RESPONSE = {
    "status": "ok",
    "message": {
        "DOI": "10.1136/bmjopen-2020-038902",
        "title": [
            "Coffee consumption and risk of prostate cancer: a systematic review and meta-analysis"
        ],
        "author": [
            {"given": "Xiaonan", "family": "Chen"},
            {"given": "Yufeng", "family": "Zhao"},
        ],
        "container-title": ["BMJ Open"],
        "publisher": "BMJ",
        "published-online": {"date-parts": [[2021, 1, 11]]},
        "type": "journal-article",
        "URL": "https://doi.org/10.1136/bmjopen-2020-038902",
    },
}


class RecordingFetcher:
    def __init__(self, response: dict | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def __call__(self, path: str, params: dict[str, str], headers: dict[str, str]) -> dict:
        self.calls.append((path, dict(params), dict(headers)))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def publication(*, doi: str | None = "10.1136/bmjopen-2020-038902", title: str | None = None) -> Publication:
    return Publication(
        pmid="33431520",
        title=title or "Coffee consumption and risk of prostate cancer: a systematic review and meta-analysis.",
        authors=("Chen X", "Zhao Y"),
        journal="BMJ open",
        publication_date="2021 Jan 11",
        doi=doi,
        url="https://pubmed.ncbi.nlm.nih.gov/33431520/",
        matched_queries=("33431520[pmid]",),
    )


class CrossrefTests(unittest.TestCase):
    def test_fetches_and_normalizes_crossref_work(self) -> None:
        fetcher = RecordingFetcher(CROSSREF_RESPONSE)
        client = CrossrefClient(email="team@example.org", fetch_json=fetcher)

        work = client.fetch_work("10.1136/bmjopen-2020-038902")

        self.assertEqual(work.authors, ("Xiaonan Chen", "Yufeng Zhao"))
        self.assertEqual(work.publication_date, "2021-01-11")
        self.assertEqual(work.journal, "BMJ Open")
        self.assertEqual(fetcher.calls[0][1], {"mailto": "team@example.org"})
        self.assertIn("mailto:team@example.org", fetcher.calls[0][2]["User-Agent"])

    def test_normalizes_retraction_updates(self) -> None:
        response = {
            **CROSSREF_RESPONSE,
            "message": {
                **CROSSREF_RESPONSE["message"],
                "updated-by": [
                    {
                        "type": "retraction",
                        "label": "Retraction",
                        "source": "retraction-watch",
                        "DOI": "10.1000/retraction",
                        "record-id": 42,
                    }
                ],
            },
        }

        work = CrossrefClient(fetch_json=RecordingFetcher(response)).fetch_work(
            "10.1136/bmjopen-2020-038902"
        )

        self.assertEqual(work.updates[0].update_type, "retraction")
        self.assertEqual(work.updates[0].source, "retraction-watch")
        self.assertEqual(work.updates[0].record_id, "42")

    def test_verifies_matching_doi_and_title(self) -> None:
        client = CrossrefClient(fetch_json=RecordingFetcher(CROSSREF_RESPONSE))

        result = verify_publication_identity(publication(), client)

        self.assertEqual(result.status, "VERIFIED")
        self.assertGreaterEqual(result.title_similarity or 0, 0.85)

    def test_requires_review_when_titles_diverge(self) -> None:
        client = CrossrefClient(fetch_json=RecordingFetcher(CROSSREF_RESPONSE))

        result = verify_publication_identity(
            publication(title="A completely unrelated article title."),
            client,
        )

        self.assertEqual(result.status, "REVIEW_REQUIRED")

    def test_skips_publication_without_doi(self) -> None:
        fetcher = RecordingFetcher(CROSSREF_RESPONSE)

        result = verify_publication_identity(
            publication(doi=None),
            CrossrefClient(fetch_json=fetcher),
        )

        self.assertEqual(result.status, "NOT_CHECKED")
        self.assertEqual(fetcher.calls, [])

    def test_reports_doi_not_found(self) -> None:
        client = CrossrefClient(
            fetch_json=RecordingFetcher(CrossrefNotFoundError("missing"))
        )

        result = verify_publication_identity(publication(), client)

        self.assertEqual(result.status, "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
