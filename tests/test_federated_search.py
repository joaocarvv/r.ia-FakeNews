import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    SCIELO_SOURCE_LIST_FILTER,
    FederatedSearchEngine,
    FederatedSearchError,
    OpenAlexClient,
    OpenAlexSearchProvider,
    ProviderSearchResult,
    RetrievalError,
    ScieloSearchProvider,
    ScientificWork,
    SearchPlan,
    SourceRank,
    deduplicate_works,
    normalize_doi,
)


def work(
    source,
    identifier,
    *,
    title="Coffee and prostate cancer",
    doi=None,
    pmid=None,
    author="Silva A",
    year="2024",
    query="coffee prostate cancer",
    rank=1,
):
    return ScientificWork(
        title=title,
        authors=(author,) if author else (),
        journal="Journal",
        publication_date=year,
        doi=doi,
        pmid=pmid,
        url=f"https://example.org/{identifier}",
        matched_queries=(query,),
        sources=(source,),
        source_ids=((source, identifier),),
        source_ranks=(SourceRank(source, query, rank),),
    )


class ProviderStub:
    def __init__(self, name, by_query=None, error=None):
        self.name = name
        self.by_query = by_query or {}
        self.error = error
        self.calls = []

    def search(self, query, *, max_results):
        self.calls.append((query, max_results))
        if self.error:
            raise RetrievalError(self.error)
        works = tuple(self.by_query.get(query, ()))[:max_results]
        return ProviderSearchResult(self.name, query, len(works), works)


class FederatedDeduplicationTests(unittest.TestCase):
    def test_normalizes_common_doi_forms(self):
        self.assertEqual(normalize_doi("HTTPS://doi.org/10.1000/ABC.1"), "10.1000/abc.1")
        self.assertEqual(normalize_doi("doi: 10.1000/ABC.1."), "10.1000/abc.1")

    def test_merges_doi_and_preserves_all_provenance(self):
        records = [
            work("PubMed", "101", doi="10.1000/ABC", pmid="101", rank=2),
            work("OpenAlex", "W1", doi="https://doi.org/10.1000/abc", rank=1),
            work("SciELO (via OpenAlex)", "W2", doi="10.1000/abc", rank=3),
        ]

        result = deduplicate_works(
            records,
            source_order=("PubMed", "OpenAlex", "SciELO (via OpenAlex)"),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].pmid, "101")
        self.assertEqual(result[0].doi, "10.1000/abc")
        self.assertEqual(
            result[0].sources,
            ("PubMed", "OpenAlex", "SciELO (via OpenAlex)"),
        )
        self.assertEqual(len(result[0].source_ranks), 3)

    def test_uses_exact_normalized_title_year_and_first_author_as_fallback(self):
        records = [
            work("PubMed", "101", pmid="101", title="Café e câncer: revisão"),
            work(
                "OpenAlex",
                "W1",
                title="Cafe e cancer revisao",
                doi="10.1000/review",
            ),
        ]

        result = deduplicate_works(records, source_order=("PubMed", "OpenAlex"))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].pmid, "101")
        self.assertEqual(result[0].doi, "10.1000/review")

    def test_does_not_merge_same_title_with_different_year_or_author(self):
        records = [
            work("PubMed", "101", pmid="101", author="Silva A", year="2023"),
            work("OpenAlex", "W1", author="Souza B", year="2024"),
        ]

        self.assertEqual(len(deduplicate_works(records)), 2)

    def test_transitively_connects_doi_and_pmid_records(self):
        records = [
            work("PubMed", "101", pmid="101"),
            work("OpenAlex", "W1", pmid="101", doi="10.1000/x"),
            work("SciELO (via OpenAlex)", "W2", doi="10.1000/x"),
        ]

        self.assertEqual(len(deduplicate_works(records)), 1)


class OpenAlexProviderTests(unittest.TestCase):
    def test_normalizes_openalex_record_and_pmid(self):
        calls = []

        def fetcher(url, params):
            calls.append((url, dict(params)))
            return {
                "meta": {"count": 7},
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "display_name": "Coffee consumption and cancer",
                        "doi": "https://doi.org/10.1000/COFFEE",
                        "publication_date": "2024-02-01",
                        "ids": {
                            "pmid": "https://pubmed.ncbi.nlm.nih.gov/12345",
                        },
                        "authorships": [
                            {"author": {"display_name": "Ana Silva"}},
                        ],
                        "primary_location": {
                            "landing_page_url": "https://journal.example/article",
                            "source": {"display_name": "Health Journal"},
                        },
                    }
                ],
            }

        provider = OpenAlexSearchProvider(OpenAlexClient(fetch_json=fetcher))
        result = provider.search("coffee cancer", max_results=5)

        self.assertEqual(result.total_matches, 7)
        self.assertEqual(result.works[0].pmid, "12345")
        self.assertEqual(result.works[0].doi, "10.1000/coffee")
        self.assertEqual(result.works[0].authors, ("Ana Silva",))
        self.assertEqual(calls[0][1]["sort"], "relevance_score:desc")

    def test_scielo_provider_uses_official_openalex_source_list_filter(self):
        calls = []

        def fetcher(url, params):
            calls.append(dict(params))
            return {"meta": {"count": 0}, "results": []}

        provider = ScieloSearchProvider(OpenAlexClient(fetch_json=fetcher))
        result = provider.search("saúde", max_results=3)

        self.assertEqual(result.source, "SciELO (via OpenAlex)")
        self.assertEqual(calls[0]["filter"], SCIELO_SOURCE_LIST_FILTER)

    def test_retries_a_transient_openalex_http_error(self):
        class Response(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        responses = [
            HTTPError("https://api.openalex.org/works", 503, "down", {}, None),
            Response(b'{"meta": {"count": 0}, "results": []}'),
        ]
        sleeps = []

        def next_response(*args, **kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with patch(
            "fatofake.federated_search.urlopen",
            side_effect=next_response,
        ):
            client = OpenAlexClient(
                max_attempts=2,
                retry_delay=0.25,
                sleep=sleeps.append,
            )
            total, records = client.search_works("coffee", max_results=1)

        self.assertEqual((total, records), (0, ()))
        self.assertEqual(sleeps, [0.25])


class FederatedSearchEngineTests(unittest.TestCase):
    def test_combines_sources_deduplicates_and_separates_unresolved_works(self):
        query = "coffee prostate cancer"
        pubmed = ProviderStub(
            "PubMed",
            {query: [work("PubMed", "101", doi="10.1000/x", pmid="101")]},
        )
        openalex = ProviderStub(
            "OpenAlex",
            {
                query: [
                    work("OpenAlex", "W1", doi="10.1000/x"),
                    work(
                        "OpenAlex",
                        "W2",
                        title="External-only study",
                        doi="10.1000/y",
                        author="Costa B",
                    ),
                ]
            },
        )
        scielo = ProviderStub("SciELO (via OpenAlex)", {query: []})
        plan = SearchPlan(claim="claim", queries=(query,))

        result = FederatedSearchEngine([pubmed, openalex, scielo]).search(
            plan, max_results_per_query=5
        )

        self.assertEqual(len(result.works), 2)
        self.assertEqual([item.pmid for item in result.publications], ["101"])
        self.assertEqual(len(result.unresolved_works), 1)
        self.assertEqual(len(result.query_results), 3)
        self.assertIn("OpenAlex", result.works[0].sources)

    def test_isolates_one_source_failure(self):
        query = "query"
        failing = ProviderStub("OpenAlex", error="controlled failure")
        working = ProviderStub(
            "PubMed",
            {query: [work("PubMed", "1", pmid="1")]},
        )

        result = FederatedSearchEngine([failing, working]).search(
            SearchPlan(claim="claim", queries=(query,))
        )

        self.assertEqual(len(result.publications), 1)
        self.assertEqual(result.failures[0].source, "OpenAlex")

    def test_fails_only_when_every_source_query_fails(self):
        engine = FederatedSearchEngine(
            [
                ProviderStub("PubMed", error="down"),
                ProviderStub("OpenAlex", error="down"),
            ]
        )

        with self.assertRaises(FederatedSearchError):
            engine.search(SearchPlan(claim="claim", queries=("query",)))

    def test_requires_unique_provider_names(self):
        with self.assertRaises(RetrievalError):
            FederatedSearchEngine([ProviderStub("same"), ProviderStub("same")])


if __name__ == "__main__":
    unittest.main()
