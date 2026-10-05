import json
import unittest
from unittest.mock import Mock

from fatofake.api import AnalysisJobService, create_app
from fatofake.input_validation import InputValidationError
from fatofake.pubmed import Publication, PubMedError
from fatofake.topic_search import PubMedTopicSearch


class TopicSearchTests(unittest.TestCase):
    def client(self):
        client = Mock()
        client.search_ids.return_value = (20, ("123",))
        client.fetch_summaries.return_value = (
            Publication("123", "Title from PubMed", (), "Journal", "2025", None,
                        "https://pubmed.ncbi.nlm.nih.gov/123/", (),
                        publication_types=("Journal Article",), pmcid="PMC123",
                        languages=("eng",)),
        )
        return client

    def gateway(self, queries):
        gateway = Mock(model_name="controlled-model")
        gateway._response_text.return_value = json.dumps({"queries": queries})
        return gateway

    def test_direct_search_without_llm_uses_pubmed_metadata(self):
        client = self.client()
        result = PubMedTopicSearch(client).search("diabetes exercise")
        client.search_ids.assert_called_once_with(
            "(diabetes exercise) AND (medline[sb])", max_results=20, start=0
        )
        self.assertEqual(result["mode"], "DIRECT")
        self.assertEqual(result["articles"][0]["title"], "Title from PubMed")
        self.assertEqual(result["articles"][0]["publication_type_labels"], ["Artigo científico"])
        self.assertTrue(result["articles"][0]["has_full_text"])
        self.assertTrue(result["articles"][0]["is_medline"])
        self.assertEqual(result["articles"][0]["language_labels"], ["Inglês"])
        self.assertEqual(result["pagination"]["total_results"], 20)

    def test_assisted_queries_preserve_original_and_deduplicate_articles(self):
        client = self.client()
        gateway = self.gateway(["diabetes AND exercise", "diabetes AND exercise", "diabetes AND physical activity"])
        result = PubMedTopicSearch(client, gateway).search("exercício e diabetes", article_type="REVIEWS")
        self.assertEqual(result["mode"], "ASSISTED")
        self.assertEqual(len(result["query_results"]), 1)
        self.assertIn("exercício e diabetes", result["query_results"][0]["query"])
        self.assertIn('"Systematic Review"[Publication Type]', result["query_results"][0]["query"])
        client.fetch_summaries.assert_called_once()
        self.assertEqual(client.fetch_summaries.call_args.args[0], ("123",))
        self.assertEqual(len(result["articles"]), 1)
        self.assertNotIn("tools", gateway._post_json.call_args.args[1])

    def test_llm_failure_falls_back_to_original_query(self):
        client = self.client()
        gateway = self.gateway([])
        gateway._post_json.side_effect = RuntimeError("controlled failure")
        result = PubMedTopicSearch(client, gateway).search("diabetes")
        self.assertEqual(result["mode"], "DIRECT_FALLBACK")
        client.search_ids.assert_called_once_with(
            "(diabetes) AND (medline[sb])", max_results=20, start=0
        )

    def test_pubmed_failure_is_reported(self):
        client = self.client()
        client.search_ids.side_effect = PubMedError("down")
        with self.assertRaises(PubMedError):
            PubMedTopicSearch(client, self.gateway(["exercise diabetes"])).search("diabetes")

    def test_pagination_and_full_text_filter_are_sent_to_pubmed(self):
        client = self.client()
        result = PubMedTopicSearch(client).search(
            "diabetes", availability="PMC_FULL_TEXT", page=2, page_size=10
        )
        query = client.search_ids.call_args.args[0]
        self.assertIn('"pubmed pmc"[Filter]', query)
        client.search_ids.assert_called_once_with(query, max_results=10, start=10)
        self.assertEqual(result["pagination"]["page"], 2)
        self.assertEqual(result["pagination"]["first_result"], 11)

    def test_language_filter_is_applied_by_pubmed(self):
        client = self.client()
        result = PubMedTopicSearch(client).search("diabetes", language="PORTUGUESE")
        query = client.search_ids.call_args.args[0]
        self.assertIn('"Portuguese"[Language]', query)
        self.assertEqual(result["filters"]["language"], "PORTUGUESE")

    def test_translates_result_titles_and_preserves_the_original(self):
        client = self.client()
        gateway = self.gateway(["diabetes exercise"])
        gateway._response_text.side_effect = [
            json.dumps({"queries": ["diabetes exercise"]}),
            json.dumps({"items": [{"pmid": "123", "title_pt": "Título traduzido do PubMed"}]}),
        ]

        result = PubMedTopicSearch(client, gateway).search("diabetes")

        self.assertEqual(result["articles"][0]["title_pt"], "Título traduzido do PubMed")
        self.assertEqual(result["articles"][0]["title"], "Title from PubMed")

    def test_prepared_query_keeps_later_pages_stable_without_calling_llm(self):
        client = self.client()
        gateway = self.gateway(["query that must not be generated"])
        result = PubMedTopicSearch(client, gateway).search(
            "diabetes", page=2,
            prepared_query='(diabetes) AND ("pubmed pmc"[Filter]) AND (medline[sb])',
        )
        self.assertEqual(gateway._post_json.call_count, 1)
        self.assertIn("Traduza fielmente", gateway._post_json.call_args.args[1]["contents"][0]["parts"][0]["text"])
        client.search_ids.assert_called_once_with(
            '(diabetes) AND ("pubmed pmc"[Filter]) AND (medline[sb])',
            max_results=20,
            start=20,
        )
        self.assertEqual(result["mode"], "PAGINATED")

    def test_empty_search_does_not_fetch_metadata(self):
        client = self.client()
        client.search_ids.return_value = (0, ())
        self.assertEqual(PubMedTopicSearch(client).search("diabetes")["articles"], [])
        client.fetch_summaries.assert_not_called()

    def test_invalid_inputs_do_not_call_external_services(self):
        client = self.client()
        gateway = self.gateway([])
        search = PubMedTopicSearch(client, gateway)
        for topic in (None, {}, "x", "a" * 301):
            with self.assertRaises(InputValidationError):
                search.search(topic)
        with self.assertRaises(InputValidationError):
            search.search("diabetes", article_type="UNKNOWN")
        with self.assertRaises(InputValidationError):
            search.search("diabetes", availability="UNKNOWN")
        with self.assertRaises(InputValidationError):
            search.search("diabetes", indexing="UNKNOWN")
        with self.assertRaises(InputValidationError):
            search.search("diabetes", language="UNKNOWN")
        with self.assertRaises(InputValidationError):
            search.search("diabetes", page=0)
        with self.assertRaises(InputValidationError):
            search.search("diabetes", prepared_query="(diabetes)")
        client.search_ids.assert_not_called()
        gateway._post_json.assert_not_called()

    def test_api_contract_and_pubmed_outage(self):
        service = AnalysisJobService(Mock())
        self.addCleanup(service.close)
        search = PubMedTopicSearch(self.client())
        client = create_app(service, article_search=search).test_client()
        response = client.post("/api/v1/pubmed-search", json={"topic": "diabetes"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["source"], "PubMed")
        self.assertEqual(client.post("/api/v1/pubmed-search", json={"topic": "x"}).status_code, 400)
        self.assertEqual(client.post("/api/v1/pubmed-search", data="text").status_code, 415)
        search.client.search_ids.side_effect = PubMedError("down")
        self.assertEqual(client.post("/api/v1/pubmed-search", json={"topic": "diabetes"}).status_code, 502)
        self.assertEqual(create_app(service).test_client().post("/api/v1/pubmed-search", json={"topic": "diabetes"}).status_code, 503)


if __name__ == "__main__":
    unittest.main()
