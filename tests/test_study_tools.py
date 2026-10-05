import base64
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.api import AnalysisJobService, AnalysisJobStatus, SQLiteAnalysisJobStore, create_app
from fatofake.document_parsing import ParsedPage
from fatofake.full_text_sources import FullTextLocator
from fatofake.gemini_evidence import GeminiEvidenceAssessment
from fatofake.open_access_content import sections_from_markdown
from fatofake.retrieval_preview import RetrievalPreviewRunner, StudyTools, work_key

from test_api import ImmediateExecutor, RunnerStub


def claim_result():
    return {
        "input": {"claim": "Tratamento reduz dor."},
        "search": {"candidate_count": 2, "reranking": {"rejected": [{"doi": "10.1/rejected"}]}},
        "articles": [
            {
                "pmid": None,
                "doi": "10.1/scielo",
                "work_key": "doi:10.1/scielo",
                "title": "SciELO study",
                "url": "https://doi.org/10.1/scielo",
                "publication_date": "2015",
                "access_level": "METADATA_ONLY",
                "quality": {"study_design": "NOT_ASSESSED"},
                "assessments": [],
                "retrieval": {"sources": ["SciELO (via OpenAlex)"]},
            }
        ],
        "reproducibility": {"queries": ["pain AND treatment"], "executed_at": "2026-01-01T00:00:00"},
    }


class ParserStub:
    def parse_pdf(self, content):
        text = "Results. Pain decreased with treatment compared with placebo in 120 adults."
        return SimpleNamespace(text=text, page_count=1, pages=(ParsedPage(1, text),))


class AnalyzerStub:
    model_name = "stub"

    def __init__(self):
        self.calls = []

    def analyze(self, claim, documents, claim_profile=None):
        self.calls.append((claim, documents, claim_profile))
        passage = documents[0].passages[0]
        return (
            GeminiEvidenceAssessment(
                pmid=documents[0].pmid,
                relation="SUPPORTS",
                confidence=0.9,
                rationale="Compatível.",
                evidence_quote="Pain decreased with treatment",
                study_design="RANDOMIZED_CLINICAL_TRIAL",
                model_name="stub",
                passage_id=passage.passage_id,
                evidence_section=passage.section,
                evidence_page=passage.page_number,
                content_scope=passage.content_scope,
                study_row={"title_pt": "Estudo SciELO", "comparability": "DIRECT", "rob_overall": "LOW"},
            ),
        )


class SearchEngineStub:
    def search(self, plan, max_results_per_query=5):
        works = [
            SimpleNamespace(doi="10.1/scielo", pmid=None, url="https://doi.org/10.1/scielo",
                            title="SciELO study", publication_date="2015", journal=None, sources=("OpenAlex",)),
            SimpleNamespace(doi="10.1/rejected", pmid=None, url="https://doi.org/10.1/rejected",
                            title="Old rejected", publication_date="2010", journal=None, sources=("OpenAlex",)),
            SimpleNamespace(doi="10.1/new", pmid="999", url="https://pubmed.ncbi.nlm.nih.gov/999/",
                            title="New trial", publication_date="2026 Mar", journal="J", sources=("PubMed",)),
        ]
        return SimpleNamespace(works=works)


def tools():
    analyzer = AnalyzerStub()
    runner = RetrievalPreviewRunner(SearchEngineStub(), evidence_analyzer=analyzer)
    return StudyTools(runner, ParserStub()), analyzer


class FullTextLocatorTests(unittest.TestCase):
    def test_collects_open_copies_pdf_first(self):
        responses = {
            "europepmc": {
                "resultList": {
                    "result": [
                        {
                            "abstractText": "Resumo do estudo.",
                            "pmcid": "PMC1",
                            "fullTextUrlList": {
                                "fullTextUrl": [
                                    {"availabilityCode": "OA", "documentStyle": "html", "url": "https://europepmc.org/a"},
                                    {"availabilityCode": "S", "documentStyle": "pdf", "url": "https://paywall.example/a.pdf"},
                                ]
                            },
                        }
                    ]
                }
            },
            "unpaywall": {"oa_locations": [{"url_for_pdf": "https://repo.example/a.pdf", "url_for_landing_page": "https://repo.example/a"}]},
            "semanticscholar": {"openAccessPdf": {"url": "https://repo.example/a.pdf"}},
        }

        def get_json(url):
            return next((value for key, value in responses.items() if key in url), {})

        lead = FullTextLocator(email="a@b.c", get_json=get_json).locate("10.1/x")

        self.assertEqual(lead.abstract, "Resumo do estudo.")
        self.assertEqual(lead.pmcid, "PMC1")
        urls = [item.url for item in lead.candidates]
        self.assertEqual(urls[0], "https://repo.example/a.pdf")
        self.assertNotIn("https://paywall.example/a.pdf", urls)
        self.assertEqual(len(urls), len(set(urls)))

    def test_unpaywall_skipped_without_email_and_failures_tolerated(self):
        def get_json(url):
            raise OSError("offline")

        lead = FullTextLocator(get_json=get_json).locate("10.1/x")

        self.assertEqual(lead.candidates, ())
        self.assertNotIn("Unpaywall", lead.consulted)

    def test_markdown_sections(self):
        markdown = "# Methods\n" + "a " * 60 + "\n## Results\n" + "b " * 60
        self.assertEqual([item.title for item in sections_from_markdown(markdown)], ["Methods", "Results"])


class OpenAccessArticleResolverTests(unittest.TestCase):
    def test_resolves_submitted_doi_from_open_copy_and_skips_failures(self):
        from fatofake.article_ingestion import OpenAccessArticleResolver, validate_article_submission
        from fatofake.full_text_sources import FullTextCandidate, FullTextLead
        from fatofake.open_access_content import OpenAccessContentError
        from fatofake.pmc import ArticleContent, ContentSection

        class Locator:
            def locate(self, doi, known_url=None):
                return FullTextLead(
                    candidates=(
                        FullTextCandidate("https://blocked.example/a.pdf", "Unpaywall", True),
                        FullTextCandidate("https://www.scielo.br/a", "Europe PMC", False),
                    )
                )

        class Client:
            def retrieve(self, *, pmid, pmcid, doi, pubmed_url, full_text_url, abstract):
                if "blocked" in full_text_url:
                    raise OpenAccessContentError("robots")
                return ArticleContent(
                    pmid=pmid, pmcid=None, doi=doi, abstract=None, full_text="Texto integral.",
                    sections=(ContentSection("Resultados", "Texto integral."),),
                    access_level="OPEN_ACCESS_FULL_TEXT", pubmed_url=pubmed_url, pmc_url=full_text_url,
                )

        resolved = OpenAccessArticleResolver(Locator(), Client()).resolve(
            validate_article_submission({"article_reference": "10.1590/x"})
        )

        self.assertEqual(resolved.content_scope, "OPEN_ACCESS_FULL_TEXT")
        self.assertEqual(resolved.sections, (("Resultados", "Texto integral."),))
        self.assertEqual(resolved.parser_name, "open-access:Europe PMC")
        self.assertEqual(resolved.doi, "10.1590/x")


class StudyToolsTests(unittest.TestCase):
    def test_work_key_falls_back_to_doi(self):
        self.assertEqual(work_key(SimpleNamespace(pmid="1", doi="x")), "1")
        self.assertEqual(work_key(SimpleNamespace(pmid=None, doi="10.1/x")), "doi:10.1/x")
        self.assertIsNone(work_key(SimpleNamespace(pmid=None, doi=None)))

    def test_reassesses_user_pdf_and_recomputes_synthesis(self):
        study_tools, analyzer = tools()

        updated = study_tools.reassess_with_full_text(
            claim_result(),
            claim_text="Tratamento reduz dor.",
            claim_profile={"population": "Adultos"},
            study_key="doi:10.1/scielo",
            pdf_bytes=b"%PDF",
        )

        article = updated["articles"][0]
        self.assertEqual(article["access_level"], "USER_PROVIDED_FULL_TEXT")
        self.assertEqual(article["assessments"][0]["relation"], "SUPPORTS")
        self.assertEqual(updated["weighted_evidence"]["verdict"]["code"], "WEIGHTED_SUPPORT")
        self.assertEqual(updated["weighted_evidence"]["rows"][0]["title_pt"], "Estudo SciELO")
        self.assertEqual(analyzer.calls[0][2], {"population": "Adultos"})

    def test_rejects_unknown_study(self):
        study_tools, _ = tools()
        with self.assertRaises(Exception):
            study_tools.reassess_with_full_text(
                claim_result(), claim_text="x", claim_profile=None, study_key="999", pdf_bytes=b"%PDF"
            )

    def test_finds_only_unseen_studies(self):
        study_tools, _ = tools()

        updates = study_tools.find_new_studies(claim_result())

        self.assertEqual(updates["new_study_count"], 1)
        self.assertEqual(updates["new_studies"][0]["title"], "New trial")
        self.assertTrue(updates["new_studies"][0]["published_after_analysis"])


class StudyToolsApiTests(unittest.TestCase):
    def service(self, store):
        study_tools, _ = tools()
        return AnalysisJobService(
            RunnerStub(),
            store=store,
            executor=ImmediateExecutor(),
            result_serializer=lambda result: result,
            study_tools=study_tools,
        )

    def completed_job(self, store):
        from fatofake.input_validation import validate_analysis_input

        job = store.create(validate_analysis_input("Alegação válida para análise.", None))
        store.transition(job.analysis_id, status=AnalysisJobStatus.RUNNING, progress=10)
        store.transition(
            job.analysis_id,
            status=AnalysisJobStatus.SUCCEEDED,
            progress=100,
            result={
                "claim_analyses": [
                    {"claim_id": "claim-01", "claim": {"text": "Tratamento reduz dor."}, "result": claim_result()}
                ]
            },
        )
        return job.analysis_id

    def test_endpoints_update_persisted_result(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAnalysisJobStore(Path(directory) / "jobs.sqlite3")
            service = self.service(store)
            client = create_app(service).test_client()
            analysis_id = self.completed_job(store)

            uploaded = client.post(
                f"/api/v1/analyses/{analysis_id}/claims/claim-01/studies/full-text",
                json={
                    "study_key": "doi:10.1/scielo",
                    "article_file": {
                        "name": "s.pdf",
                        "mime_type": "application/pdf",
                        "data_base64": base64.b64encode(b"%PDF-1.4").decode(),
                    },
                },
            )
            checked = client.post(f"/api/v1/analyses/{analysis_id}/new-studies", json={})
            watched = client.put(f"/api/v1/analyses/{analysis_id}/watch", json={"enabled": True})
            cycle = service.run_watch_cycle()
            stored = store.get(analysis_id).result

        self.assertEqual(uploaded.status_code, 200)
        claim = uploaded.get_json()["result"]["claim_analyses"][0]["result"]
        self.assertEqual(claim["articles"][0]["access_level"], "USER_PROVIDED_FULL_TEXT")
        self.assertEqual(checked.status_code, 200)
        self.assertEqual(checked.get_json()["result"]["updates"]["new_study_count"], 1)
        self.assertTrue(watched.get_json()["result"]["watch"]["enabled"])
        self.assertEqual(cycle, 1)
        self.assertEqual(
            stored["claim_analyses"][0]["result"]["articles"][0]["access_level"],
            "USER_PROVIDED_FULL_TEXT",
        )

    def test_rejects_non_pdf_and_unfinished_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAnalysisJobStore(Path(directory) / "jobs.sqlite3")
            client = create_app(self.service(store)).test_client()
            analysis_id = self.completed_job(store)
            image = client.post(
                f"/api/v1/analyses/{analysis_id}/claims/claim-01/studies/full-text",
                json={
                    "study_key": "doi:10.1/scielo",
                    "article_file": {"name": "a.png", "mime_type": "image/png", "data_base64": "iVBORw=="},
                },
            )
            unknown_claim = client.post(f"/api/v1/analyses/{analysis_id}/new-studies", json={"claim_id": "x"})
            missing = client.post("/api/v1/analyses/nope/new-studies", json={})

        self.assertEqual(image.status_code, 422)
        self.assertEqual(unknown_claim.status_code, 422)
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
