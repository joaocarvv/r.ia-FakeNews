import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import PubMedClient, PubMedError, SearchPlan, search_pubmed


class QueueFetcher:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, endpoint: str, params: dict[str, str]) -> dict:
        self.calls.append((endpoint, dict(params)))
        return self.responses.pop(0)


def esearch_response(total: int, identifiers: list[str]) -> dict:
    return {"esearchresult": {"count": str(total), "idlist": identifiers}}


ESUMMARY_RESPONSE = {
    "result": {
        "uids": ["101", "202", "303"],
        "101": {
            "title": "Coffee consumption and cancer risk.",
            "authors": [{"name": "Silva A"}, {"name": "Souza B"}],
            "fulljournalname": "Journal of Coffee Research",
            "pubdate": "2025",
            "epubdate": "2025 Jan 10",
            "articleids": [
                {"idtype": "pubmed", "value": "101"},
                {"idtype": "doi", "value": "10.1000/coffee.101"},
            ],
        },
        "202": {
            "title": "Coffee and neoplasms: a systematic review.",
            "authors": [{"name": "Costa C"}],
            "source": "Health Rev",
            "pubdate": "2024",
            "articleids": [{"idtype": "pubmed", "value": "202"}],
        },
        "303": {
            "title": "Dietary exposures and cancer.",
            "authors": [],
            "source": "Nutrition",
            "pubdate": "2023",
            "articleids": [{"idtype": "pubmed", "value": "303"}],
        },
    }
}


class SearchPubMedTests(unittest.TestCase):
    def test_searches_deduplicates_and_normalizes_articles(self) -> None:
        fetcher = QueueFetcher(
            [
                esearch_response(20, ["101", "202"]),
                esearch_response(8, ["202", "303"]),
                ESUMMARY_RESPONSE,
            ]
        )
        client = PubMedClient(fetch_json=fetcher)
        plan = SearchPlan(
            claim="Tomar café aumenta o risco de câncer.",
            queries=("coffee cancer risk", "coffee neoplasms"),
        )

        result = search_pubmed(plan, client, max_results_per_query=2)

        self.assertEqual([item.total_matches for item in result.query_results], [20, 8])
        self.assertEqual([item.pmid for item in result.publications], ["101", "202", "303"])
        self.assertEqual(result.publications[0].doi, "10.1000/coffee.101")
        self.assertEqual(result.publications[0].authors, ("Silva A", "Souza B"))
        self.assertEqual(
            result.publications[1].matched_queries,
            ("coffee cancer risk", "coffee neoplasms"),
        )
        self.assertEqual([call[0] for call in fetcher.calls], [
            "esearch.fcgi",
            "esearch.fcgi",
            "esummary.fcgi",
        ])

    def test_does_not_request_summaries_when_search_is_empty(self) -> None:
        fetcher = QueueFetcher([esearch_response(0, [])])
        client = PubMedClient(fetch_json=fetcher)
        plan = SearchPlan(claim="Alegação de teste.", queries=("no results",))

        result = search_pubmed(plan, client)

        self.assertEqual(result.publications, ())
        self.assertEqual(len(fetcher.calls), 1)

    def test_rejects_invalid_esearch_response(self) -> None:
        client = PubMedClient(fetch_json=QueueFetcher([{"unexpected": {}}]))

        with self.assertRaises(PubMedError):
            client.search_ids("coffee", max_results=5)

    def test_validates_result_limit(self) -> None:
        client = PubMedClient(fetch_json=QueueFetcher([]))

        with self.assertRaises(ValueError):
            client.search_ids("coffee", max_results=0)


if __name__ == "__main__":
    unittest.main()
