import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.api import AnalysisJobService, AnalysisJobStatus, create_app
from fatofake.federated_search import (
    EuropePmcSearchProvider,
    FederatedSearchEngine,
    ProviderSearchResult,
    uses_pubmed_syntax,
)
from fatofake.full_text_sources import FullTextLocator
from fatofake.input_validation import validate_analysis_input
from fatofake.retrieval_preview import StudyTools, portuguese_keywords
from fatofake.search_preparation import SearchPlan
from fatofake.trial_registry import ClinicalTrialsRegistry

from test_api import ImmediateExecutor, RunnerStub


class SearchProviderTests(unittest.TestCase):
    def test_pubmed_tags_are_routed_only_to_pubmed(self):
        class Provider:
            def __init__(self, name, pubmed_syntax=False):
                self.name = name
                self.pubmed_syntax = pubmed_syntax
                self.queries = []

            def search(self, query, *, max_results):
                self.queries.append(query)
                return ProviderSearchResult(self.name, query, 0, ())

        pubmed, other = Provider("PubMed", True), Provider("OpenAlex")
        FederatedSearchEngine((pubmed, other)).search(
            SearchPlan(claim="x", queries=("a AND b", "(a AND b) AND Therapy/Narrow[filter]"))
        )

        self.assertEqual(len(pubmed.queries), 2)
        self.assertEqual(other.queries, ["a AND b"])
        self.assertTrue(uses_pubmed_syntax('"neoplasms"[MeSH Terms]'))
        self.assertFalse(uses_pubmed_syntax("appendix AND cancer"))

    def test_europe_pmc_normalizes_records_and_preprints(self):
        payload = {
            "hitCount": 2,
            "resultList": {
                "result": [
                    {
                        "id": "123", "source": "MED", "pmid": "123", "pmcid": "PMC9", "doi": "10.1/A",
                        "title": "Trial of X.", "authorString": "Silva A, Souza B.",
                        "journalTitle": "J", "pubYear": "2020", "isOpenAccess": "Y", "citedByCount": 4,
                    },
                    {"id": "PPR1", "source": "PPR", "title": "Preprint Y", "pubYear": "2024"},
                ]
            },
        }
        result = EuropePmcSearchProvider(fetch_json=lambda url: payload).search("x", max_results=5)

        first, second = result.works
        self.assertEqual(result.total_matches, 2)
        self.assertEqual(first.title, "Trial of X")
        self.assertEqual(first.authors, ("Silva A", "Souza B"))
        self.assertEqual(first.full_text_url, "https://europepmc.org/article/PMC/PMC9")
        self.assertEqual(second.publication_types, ("Preprint",))
        self.assertIn("europepmc.org/article/PPR/PPR1", second.url)


class LocatorAndRegistryTests(unittest.TestCase):
    def test_locator_uses_pmid_and_recovers_doi(self):
        urls = []

        def get_json(url):
            urls.append(url)
            if "europepmc" in url:
                return {"resultList": {"result": [{"doi": "10.1/old", "abstractText": "Resumo"}]}}
            if "openalex" in url:
                return {"locations": [{"is_oa": True, "pdf_url": "https://repo.example/x.pdf"}]}
            return {}

        lead = FullTextLocator(get_json=get_json).locate(None, pmid="11901711")

        self.assertIn("EXT_ID%3A11901711", urls[0])
        self.assertEqual(lead.doi, "10.1/old")
        self.assertEqual(lead.candidates[0].url, "https://repo.example/x.pdf")
        self.assertEqual(lead.candidates[0].source, "OpenAlex (repositório)")

    def test_trial_registry_summary(self):
        def get_json(url):
            if "aggFilters" in url:
                return {"totalCount": 3}
            return {
                "totalCount": 10,
                "studies": [
                    {
                        "hasResults": False,
                        "protocolSection": {
                            "identificationModule": {"nctId": "NCT1", "briefTitle": "T"},
                            "statusModule": {"overallStatus": "COMPLETED"},
                            "designModule": {"phases": ["PHASE3"], "enrollmentInfo": {"count": 100}},
                        },
                    }
                ],
            }

        summary = ClinicalTrialsRegistry(get_json=get_json).summarize(
            {"claim_type": "THERAPEUTIC", "concept_groups": [["drug x"], ["covid", "sars-cov-2"]]}
        )

        self.assertEqual(summary["registered_count"], 10)
        self.assertEqual(summary["without_results_count"], 7)
        self.assertEqual(summary["query"], '"drug x" AND (covid OR sars-cov-2)')
        self.assertEqual(summary["examples"][0]["url"], "https://clinicaltrials.gov/study/NCT1")
        self.assertIsNone(
            ClinicalTrialsRegistry(get_json=get_json).summarize({"claim_type": "PREVALENCE"})
        )


def base_claim_result():
    return {
        "input": {"claim": "x"},
        "search": {"candidate_count": 1},
        "articles": [
            {
                "pmid": "1", "doi": "10.1/known", "work_key": "1", "title": "Known",
                "publication_date": "2020", "access_level": "FULL_TEXT",
                "quality": {"study_design": "RANDOMIZED_CLINICAL_TRIAL"},
                "assessments": [{"relation": "SUPPORTS", "evidence": {}, "study_row": {"comparability": "DIRECT", "rob_overall": "LOW"}}],
                "retrieval": {"sources": ["PubMed"]},
            }
        ],
        "weighted_evidence": {"rows": [{"doi": "10.1/known", "weight": 0.85}]},
    }


class BatchResilienceTests(unittest.TestCase):
    def runner(self, fail_batches):
        from fatofake.gemini_evidence import GeminiAnalysisError, GeminiEvidenceAssessment
        from fatofake.retrieval_preview import RetrievalPreviewRunner

        class Abstracts:
            def fetch_pubmed_abstract(self, pmid):
                return f"Abstract {pmid} with results."

        class Analyzer:
            calls = 0

            def analyze(self, claim, documents):
                Analyzer.calls += 1
                if Analyzer.calls in fail_batches:
                    raise GeminiAnalysisError("HTTP 503")
                return tuple(
                    GeminiEvidenceAssessment(
                        pmid=item.pmid, relation="NEUTRAL", confidence=0.5, rationale="r",
                        evidence_quote=None, study_design="OTHER", model_name="stub",
                    )
                    for item in documents
                )

        runner = RetrievalPreviewRunner(object(), abstract_client=Abstracts(), evidence_analyzer=Analyzer(), max_analysis_articles=10)
        works = [
            SimpleNamespace(pmid=str(index), doi=None, title=f"T{index}", url=f"https://x.example/{index}")
            for index in range(1, 8)
        ]
        return runner, works

    def test_one_failed_batch_keeps_the_others(self):
        runner, works = self.runner({1})
        assessments, _failures, failure, _meta = runner._analyze_documents("claim", works)

        self.assertEqual(len(assessments), 2)
        self.assertIn("1 de 2 lote(s)", failure)

    def test_all_batches_failed_is_reported_as_unavailable(self):
        runner, works = self.runner({1, 2})
        assessments, _failures, failure, _meta = runner._analyze_documents("claim", works)
        from fatofake.evidence_table import synthesize_evidence

        verdict = synthesize_evidence([], candidate_count=7, analysis_unavailable=True)["verdict"]

        self.assertEqual(assessments, ())
        self.assertTrue(failure.startswith("ANALYSIS_UNAVAILABLE"))
        self.assertEqual(verdict["code"], "ANALYSIS_UNAVAILABLE")


class RobotsPolicyTests(unittest.TestCase):
    def test_missing_robots_allows_and_server_error_blocks(self):
        from unittest import mock
        from urllib.error import HTTPError

        from fatofake.open_access_content import OpenAccessContentClient, OpenAccessContentError

        client = OpenAccessContentClient(document_parser=None)

        def raising(code):
            def fake_urlopen(*args, **kwargs):
                raise HTTPError("https://x.example/robots.txt", code, "status", {}, None)
            return fake_urlopen

        with mock.patch("fatofake.open_access_content.urlopen", raising(404)):
            client._check_robots("https://x.example/article.pdf")
        for code in (503, 429):
            with mock.patch("fatofake.open_access_content.urlopen", raising(code)):
                with self.assertRaises(OpenAccessContentError):
                    client._check_robots("https://x.example/article.pdf")


class PubMedOutageTests(unittest.TestCase):
    def test_doi_resolution_falls_back_when_pubmed_rate_limits(self):
        from fatofake.article_ingestion import PubMedReferenceResolver, validate_article_submission
        from fatofake.pubmed import PubMedError

        class FailingPubMed:
            def search_ids(self, *args, **kwargs):
                raise PubMedError("HTTP Error 429: Too Many Requests")

        resolver = PubMedReferenceResolver(FailingPubMed(), None, None)
        submission = validate_article_submission({"article_reference": "10.1056/NEJMoa1800389"})

        # None deixa o resolvedor de acesso aberto tentar, em vez de falhar a análise.
        self.assertIsNone(resolver.resolve(submission))


class ComplementarySearchTests(unittest.TestCase):
    def runner(self):
        calls = []

        def analyze(claim, reference, **options):
            calls.append(options)
            return {
                "search": {"candidate_count": 7},
                "articles": [
                    base_claim_result()["articles"][0],
                    {
                        "pmid": "2", "doi": "10.1/new", "work_key": "2", "title": "New",
                        "publication_date": "2023", "access_level": "ABSTRACT_ONLY",
                        "quality": {"study_design": "OBSERVATIONAL"},
                        "assessments": [{"relation": "CONTRADICTS", "evidence": {}, "study_row": {"comparability": "PARTIAL"}}],
                        "retrieval": {"sources": ["Europe PMC"]},
                    },
                ],
            }

        return SimpleNamespace(analyze=analyze, evidence_analyzer=None), calls

    def test_adds_only_unseen_studies_and_resynthesizes(self):
        runner, calls = self.runner()
        result = StudyTools(runner, None).complementary_search(
            base_claim_result(),
            claim_text="Ivermectina reduz mortalidade por COVID-19 em adultos internados.",
            claim_profile={"concept_groups": [["ivermectin"], ["COVID-19"], ["mortality"]]},
        )

        self.assertEqual([item["work_key"] for item in result["articles"]], ["1", "2"])
        self.assertEqual(result["complementary"]["added_count"], 1)
        self.assertEqual(result["complementary"]["seed_doi"], "10.1/known")
        self.assertEqual(result["search"]["candidate_count"], 8)
        self.assertEqual(len(result["weighted_evidence"]["rows"]), 2)
        self.assertIn("10.1/known", calls[0]["excluded_dois"])
        self.assertEqual(calls[0]["depth"], "DEEP")
        self.assertIn("ivermectina", result["complementary"]["queries"][-1])

    def test_discards_indirect_neutral_studies(self):
        def analyze(claim, reference, **options):
            return {
                "search": {"candidate_count": 3},
                "articles": [
                    {
                        "pmid": "9", "work_key": "9", "title": "Off-topic",
                        "assessments": [{"relation": "NEUTRAL", "evidence": {}, "study_row": {"comparability": "INDIRECT"}}],
                    }
                ],
            }

        result = StudyTools(SimpleNamespace(analyze=analyze), None).complementary_search(
            base_claim_result(), claim_text="x", claim_profile={"concept_groups": [["a"], ["b"]]}
        )

        self.assertEqual(result["complementary"]["added_count"], 0)
        self.assertEqual(result["complementary"]["discarded_indirect_count"], 1)

    def test_europe_pmc_scopes_to_title_and_abstract(self):
        scoped = EuropePmcSearchProvider._scoped
        self.assertEqual(scoped("autism AND colitis"), "(TITLE:(autism AND colitis) OR ABSTRACT:(autism AND colitis))")
        self.assertEqual(scoped("10.1016/s0140-6736(97)11096-0"), "10.1016/s0140-6736(97)11096-0")
        self.assertEqual(scoped("EXT_ID:1 AND SRC:MED"), "EXT_ID:1 AND SRC:MED")

    def test_portuguese_keywords(self):
        self.assertEqual(
            portuguese_keywords("O consumo de café pode reduzir o risco de diabetes em 2 anos."),
            "consumo café reduzir risco diabetes anos",
        )

    def test_api_runs_complementary_and_source_preview(self):
        runner, _calls = self.runner()
        service = AnalysisJobService(
            RunnerStub(),
            executor=ImmediateExecutor(),
            result_serializer=lambda result: result,
            study_tools=StudyTools(runner, None),
        )
        store = service.store
        job = store.create(validate_analysis_input("Alegação válida para análise.", None))
        store.transition(
            job.analysis_id, status=AnalysisJobStatus.RUNNING, progress=10,
            workflow={
                "submission": {"reference": "10.1/sub"},
                "resolved": {"title": "Artigo", "pages": [{"page_number": 1, "text": "Texto da página."}]},
                "extracted": {"claims": [{"claim_id": "claim-01", "quote": "Texto da página", "page": 1}]},
            },
        )
        store.transition(
            job.analysis_id, status=AnalysisJobStatus.SUCCEEDED, progress=100,
            result={"claim_analyses": [{"claim_id": "claim-01", "claim": {"text": "Ivermectina reduz mortes.", "profile": {"concept_groups": [["ivermectin"], ["covid"]]}}, "result": base_claim_result()}]},
        )
        client = create_app(service).test_client()

        started = client.post(f"/api/v1/analyses/{job.analysis_id}/claims/claim-01/complementary-search", json={})
        final = client.get(f"/api/v1/analyses/{job.analysis_id}").get_json()
        source = client.get(f"/api/v1/analyses/{job.analysis_id}/source").get_json()

        self.assertEqual(started.status_code, 202)
        claim = final["result"]["claim_analyses"][0]["result"]
        self.assertEqual(claim["complementary"]["status"], "DONE")
        self.assertEqual(final["result"]["complementary"]["added_count"], 1)
        self.assertEqual(source["pages"][0]["text"], "Texto da página.")
        self.assertEqual(source["claims"][0]["quote"], "Texto da página")


if __name__ == "__main__":
    unittest.main()
