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
                        "https://pubmed.ncbi.nlm.nih.gov/123/", ()),
        )
        return client

    def gateway(self, queries):
        gateway = Mock(model_name="controlled-model")
        gateway._response_text.return_value = json.dumps({"queries": queries})
        return gateway

    def test_direct_search_without_llm_uses_pubmed_metadata(self):
        client = self.client()
        result = PubMedTopicSearch(client).search("diabetes exercise")
        client.search_ids.assert_called_once_with("diabetes exercise", max_results=5)
        self.assertEqual(result["mode"], "DIRECT")
        self.assertEqual(result["articles"][0]["title"], "Title from PubMed")

    def test_assisted_queries_preserve_original_and_deduplicate_articles(self):
        client = self.client()
        gateway = self.gateway(["diabetes AND exercise", "diabetes AND exercise", "diabetes AND physical activity"])
        result = PubMedTopicSearch(client, gateway).search("exercício e diabetes", article_type="REVIEWS")
        self.assertEqual(result["mode"], "ASSISTED")
        self.assertEqual(len(result["query_results"]), 3)
        self.assertIn("exercício e diabetes", result["query_results"][-1]["query"])
        self.assertTrue(all('"Systematic Review"[Publication Type]' in item["query"] for item in result["query_results"]))
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
        client.search_ids.assert_called_once_with("diabetes", max_results=5)

    def test_partial_search_failure_keeps_successful_results(self):
        client = self.client()
        client.search_ids.side_effect = [PubMedError("down"), (2, ("123",))]
        result = PubMedTopicSearch(client, self.gateway(["exercise diabetes"])).search("diabetes")
        self.assertEqual(result["query_results"][0]["status"], "UNAVAILABLE")
        self.assertEqual(len(result["articles"]), 1)

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
