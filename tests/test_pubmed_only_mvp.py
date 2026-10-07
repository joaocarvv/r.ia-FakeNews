import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from fatofake.article_ingestion import (
    ArticleFirstAnalysisRunner, ArticleIngestionError, ResolvedArticleDocument, validate_article_submission,
)
from fatofake.document_parsing import DocumentParsingError
from fatofake.evidence_table import synthesize_evidence
from fatofake.gemini_evidence import EvidenceDocument, GeminiEvidenceAnalyzer
from fatofake.input_validation import InputValidationError
from fatofake.retrieval_preview import GenericHealthQueryPlanner, create_pubmed_only_app
from fatofake.verification_cards import build_verification_indicators
from fatofake.whole_article_analysis import GeminiWholeArticleAnalyzer


class PubMedOnlyMvpTests(unittest.TestCase):
    def test_factory_excludes_external_sources_even_with_old_environment(self):
        external = (
            "OpenAlexClient", "OpenAlexGraphExplorer", "OpenAlexSearchProvider",
            "ScieloSearchProvider", "EuropePmcSearchProvider", "CrossrefClient",
            "FullTextLocator", "OpenAccessContentClient", "OpenAccessArticleResolver",
            "ClinicalTrialsRegistry", "Crawl4AiFetcher",
        )
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {
                "GEMINI_API_KEY": "test-key", "ENABLE_CRAWL4AI": "true",
                "ASSESS_METHODOLOGY": "true",
                "OPENALEX_API_KEY": "old-key", "UNPAYWALL_EMAIL": "old@example.org",
                "JOB_DATABASE_PATH": str(Path(directory) / "jobs.sqlite3"),
            }, clear=True))
            stack.enter_context(patch("fatofake.retrieval_preview._load_env"))
            stack.enter_context(patch("fatofake.retrieval_preview._start_watch_thread"))
            stack.enter_context(patch("fatofake.retrieval_preview.LiteParseDocumentParser", side_effect=DocumentParsingError("unavailable")))
            for name in external:
                stack.enter_context(patch(f"fatofake.retrieval_preview.{name}", side_effect=AssertionError(f"External source instantiated: {name}")))
            app = create_pubmed_only_app(project_root=Path(directory))
            service = app.extensions["fatofake_job_service"]
            try:
                self.assertEqual([provider.name for provider in service.runner.search_engine.providers], ["PubMed"])
                self.assertTrue(service.runner.search_engine.providers[0].require_medline)
                self.assertTrue(service.runner.pubmed_only)
                self.assertTrue(service.article_runner.pubmed_only)
                self.assertFalse(service.runner.evidence_analyzer.assess_methodology)
                self.assertIsNone(service.article_runner.reference_resolver.crossref_client)
                self.assertEqual(app.test_client().get("/").status_code, 200)
                # Exercita os clientes e o pipeline reais com transportes locais.
                pubmed = service.article_runner.reference_resolver.pubmed_client
                pmc = service.article_runner.reference_resolver.pmc_client
                def ncbi_json(endpoint, _params):
                    if endpoint == "esearch.fcgi":
                        return {"esearchresult": {"count": "1", "idlist": ["123456"]}}
                    if endpoint == "elink.fcgi":
                        return {"linksets": []}
                    return {"result": {"uids": ["123456"], "123456": {
                        "uid": "123456", "title": "Vitamin C reduces cold duration in adults",
                        "authors": [], "pubdate": "2025", "fulljournalname": "Controlled journal",
                        "articleids": [], "pubtype": ["Randomized Controlled Trial"],
                    }}}
                pubmed._fetch_json = ncbi_json
                pmc._fetch_json = lambda _url, _params: {"records": []}
                pmc._fetch_xml = lambda _url, _params: b'<PubmedArticleSet><PubmedArticle><MedlineCitation><Article><Abstract><AbstractText>Vitamin C reduced cold duration in adults.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
                service.runner.planner = GenericHealthQueryPlanner()
                service.runner.evidence_analyzer._post_json = lambda _url, _payload: {
                    "candidates": [{"content": {"parts": [{"text": json.dumps({"assessments": [{
                        "pmid": "123456", "relation": "SUPPORTS", "confidence": 0.8,
                        "evidence_quote": "Vitamin C reduced cold duration in adults.",
                        "study_design": "SYSTEMATIC_REVIEW_META_ANALYSIS",
                    }]})}]}}]
                }
                result = service.runner.analyze("Vitamin C reduces cold duration in adults.")
                article = result["articles"][0]
                self.assertTrue(article["is_medline"])
                self.assertEqual(article["access_level"], "ABSTRACT_ONLY")
                self.assertEqual(article["quality"]["study_design"], "RANDOMIZED_CLINICAL_TRIAL")
                self.assertEqual(article["assessments"][0]["relation"], "SUPPORTS")
                self.assertEqual(result["weighted_evidence"]["verdict"]["certainty"], "NOT_ASSESSED")
            finally:
                service.close()

    def test_unresolved_doi_does_not_reach_the_llm(self):
        extractor, resolver = Mock(), Mock()
        resolver.resolve.return_value = None
        runner = ArticleFirstAnalysisRunner(extractor, Mock(), resolver, pubmed_only=True)
        with self.assertRaisesRegex(ArticleIngestionError, "envie o PDF"):
            runner.prepare_article(validate_article_submission({"article_reference": "10.1000/missing"}))
        extractor.extract.assert_not_called()

    def test_only_article_links_and_identifiers_are_accepted(self):
        for reference in ("123456", "10.1000/test", "https://doi.org/10.1000/test", "https://pubmed.ncbi.nlm.nih.gov/123456/"):
            self.assertIsNotNone(validate_article_submission({"article_reference": reference}))
        for reference in ("https://publisher.org/article", "https://pubmed.ncbi.nlm.nih.gov/", "https://www.ncbi.nlm.nih.gov/books/12345", "https://pubmed.ncbi.nlm.nih.gov.evil.org/123456/"):
            with self.assertRaises(InputValidationError):
                validate_article_submission({"article_reference": reference})

    def test_factual_fields_require_literal_source_and_keep_provenance(self):
        text = "A sample of 240 adults received vitamin C. Symptoms improved."
        def post(_url, payload):
            properties = payload["generationConfig"]["responseSchema"]["properties"]["assessments"]["items"]["properties"]
            self.assertNotIn("study_design", properties)
            self.assertNotIn("rob_overall", properties["study_row"]["properties"])
            output = {"assessments": [{
                "pmid": "123", "relation": "SUPPORTS", "confidence": 0.9,
                "evidence_quote": "Symptoms improved.", "study_design": "RANDOMIZED_CLINICAL_TRIAL",
                "study_row": {"sample_size": "240", "population": "adults", "comparator": "placebo", "rob_overall": "LOW", "comparability": "DIRECT"},
            }]}
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(output)}]}}]}
        analyzer = GeminiEvidenceAnalyzer("test-key", post_json=post, assess_methodology=False)
        result = analyzer.analyze("Vitamin C improves symptoms.", [EvidenceDocument("123", "Trial", text, "https://pubmed.ncbi.nlm.nih.gov/123/")])[0]
        self.assertEqual(result.study_design, "UNKNOWN")
        self.assertEqual(result.study_row["sample_size"], "240")
        self.assertEqual(result.study_row["comparator"], "")
        self.assertNotIn("rob_overall", result.study_row)
        self.assertEqual(result.study_row["field_sources"]["sample_size"]["source_url"], "https://pubmed.ncbi.nlm.nih.gov/123/")

    def test_no_methodological_weight_or_certainty_and_retracted_study_excluded(self):
        articles = [
            {"title": "Study", "quality": {"study_design": "RANDOMIZED_CLINICAL_TRIAL", "level": "HIGH", "is_retracted": retracted},
             "assessments": [{"relation": relation, "evidence": {"text": "Literal quote"}, "study_row": {"comparability": "DIRECT", "rob_overall": "LOW"}}]}
            for retracted, relation in ((False, "SUPPORTS"), (True, "CONTRADICTS"))
        ]
        result = synthesize_evidence(articles, candidate_count=2, assess_methodology=False)
        self.assertEqual(result["verdict"]["certainty"], "NOT_ASSESSED")
        self.assertIsNone(result["verdict"]["certainty_label"])
        self.assertEqual([row["weight"] for row in result["rows"]], [1.0, 0.0])
        self.assertTrue(all(row["rob_overall"] is None for row in result["rows"]))
        indicators = build_verification_indicators(articles=articles, research_context="CLINICAL", assess_methodology=False)
        self.assertEqual(indicators["methodological_confidence"]["level"], "NOT_EVALUATED")
        self.assertEqual(indicators["methodological_confidence"]["quality_counts"], {})

    def test_whole_article_prompt_does_not_request_methodology_judgments(self):
        prompt = GeminiWholeArticleAnalyzer._prompt(None, assess_methodology=False)
        self.assertNotIn("as limitações metodológicas que você identificar", prompt)
        self.assertIn("retorne uma lista vazia", prompt)

    def test_whole_article_discards_invented_fields_and_methodology_judgments(self):
        output = {
            "study": {"design": "Randomized trial", "sample_size": "240", "population": "children", "statistical_methods": ["Bayesian model"]},
            "limitations": ["High risk of bias"],
        }
        gateway = Mock(model_name="controlled-model", assess_methodology=False)
        gateway._post_json.return_value = output
        gateway._response_text.return_value = json.dumps(output)
        resolved = ResolvedArticleDocument(title="Study", doi=None, text="A sample of 240 adults was enrolled.", content_scope="ABSTRACT_ONLY")
        result = GeminiWholeArticleAnalyzer(gateway).analyze(
            validate_article_submission({"article_reference": "123456"}), resolved
        )
        self.assertEqual(result["study"]["sample_size"], "240")
        self.assertEqual(result["study"]["population"], None)
        self.assertEqual(result["study"]["design"], None)
        self.assertEqual(result["study"]["statistical_methods"], [])
        self.assertEqual(result["study_field_sources"]["sample_size"][0]["text"], "240")
        self.assertIn("240 adults", result["study_field_sources"]["sample_size"][0]["quote"])
        self.assertNotIn("population", result["study_field_sources"])
        self.assertEqual(result["limitations"], [])
        self.assertEqual(result["methodology_assessment"], "NOT_EVALUATED")
        self.assertNotIn("tools", gateway._post_json.call_args.args[1])


    def test_factual_table_does_not_expose_unverified_data_or_inferred_design(self):
        articles = [{
            "pmid": "123", "title": "Study", "publication_types": ["Multicenter Study"],
            "quality": {"study_design": "OBSERVATIONAL"},
            "assessments": [{"relation": "NEUTRAL", "study_row": {
                "population": "children", "sample_size": "999",
                "design_detail": "Randomized trial",
            }}],
        }]
        row = synthesize_evidence(articles, candidate_count=1, assess_methodology=False)["rows"][0]
        self.assertIsNone(row["population"])
        self.assertIsNone(row["sample_size"])
        self.assertIsNone(row["design_detail"])
        self.assertIsNone(row["design_label"])
        self.assertEqual(row["publication_types"], ["Multicenter Study"])
        self.assertEqual(row["publication_types_source"], "PubMed · PublicationType")

    def test_unverified_whole_article_findings_and_funding_are_omitted(self):
        output = {
            "main_findings": [{"finding": "Invented", "citations": [{"quote": "Not in text", "section": "Results"}]}],
            "funding": {"status": "REPORTED", "statement": "Invented sponsor", "citations": []},
            "strengths": ["Strong methods"], "red_flags": ["High bias"],
        }
        gateway = Mock(model_name="controlled-model", assess_methodology=False)
        gateway._post_json.return_value = output
        gateway._response_text.return_value = json.dumps(output)
        resolved = ResolvedArticleDocument(title="Study", doi=None, text="An available abstract.", content_scope="ABSTRACT_ONLY")
        report = GeminiWholeArticleAnalyzer(gateway).analyze(
            validate_article_submission({"article_reference": "123456"}), resolved
        )
        self.assertEqual(report["main_findings"], [])
        self.assertEqual(report["funding"], {})
        self.assertEqual(report["strengths"], [])
        self.assertEqual(report["red_flags"], [])


if __name__ == "__main__":
    unittest.main()
