import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.api import (
    AnalysisJobService,
    AnalysisJobStatus,
    SQLiteAnalysisJobStore,
    create_app,
)
from fatofake.article_ingestion import (
    ArticleFirstAnalysisRunner,
    ArticleSubmission,
    ExtractedArticle,
    ExtractedClaim,
    PreparedArticle,
    ResolvedArticleDocument,
)
from fatofake.document_parsing import ParsedPage

from test_api import HoldingExecutor, ImmediateExecutor, RunnerStub


def prepared_article():
    return PreparedArticle(
        submission=ArticleSubmission(
            reference="10.1000/example",
            reference_type="doi",
            file_name=None,
            mime_type=None,
            content=None,
        ),
        resolved=ResolvedArticleDocument(
            title="Estudo exemplo",
            doi="10.1000/example",
            text="Texto integral do artigo.",
            pmid="123",
            page_count=1,
            pages=(ParsedPage(1, "Texto integral do artigo."),),
            sections=(("Resultados", "O tratamento reduziu a dor."),),
            content_scope="LOCAL_PDF_FULL_TEXT",
            authors=("Silva A",),
        ),
        extracted=ExtractedArticle(
            title="Estudo exemplo",
            doi="10.1000/example",
            primary_claim="O tratamento reduziu a dor em adultos.",
            search_query="treatment pain adults",
            additional_claims=(),
            absolute_language=(),
            extraction_model="stub",
            claims=(
                ExtractedClaim(
                    claim_id="claim-01",
                    text="O tratamento reduziu a dor em adultos.",
                    search_query="treatment pain adults",
                    quote="O tratamento reduziu a dor.",
                    section="Resultados",
                    page=1,
                ),
                ExtractedClaim(
                    claim_id="claim-02",
                    text="O efeito persistiu por seis meses.",
                    search_query="treatment effect six months",
                ),
            ),
        ),
        dossier={"identity": {"status": "VERIFIED"}},
        whole_article_analysis={"status": "COMPLETED", "coverage": {}},
    )


class PreparingArticleRunnerStub:
    """Imita o runner real sem rede: prepara, pausa e pesquisa só o selecionado."""

    _claims_for = staticmethod(ArticleFirstAnalysisRunner._claims_for)

    def __init__(self):
        self.prepared_calls = []

    def analyze_article(self, submission):
        raise AssertionError("O fluxo com seleção não deve executar tudo de uma vez.")

    def prepare_article(self, submission):
        return prepared_article()

    def preparation_result(self, prepared):
        return {
            "workflow": {"stage": "CLAIM_SELECTION"},
            "submitted_article": {
                "claims": [
                    {"claim_id": claim.claim_id, "text": claim.text}
                    for claim in self._claims_for(prepared.extracted)
                ]
            },
            "whole_article_analysis": dict(prepared.whole_article_analysis),
        }

    def analyze_prepared(self, prepared, selected_claims=None, depth="QUICK"):
        self.depths = getattr(self, "depths", []) + [depth]
        self.prepared_calls.append((prepared, selected_claims))
        return {
            "claim_analyses": [
                {"claim_id": claim.claim_id, "claim": {"text": claim.text}}
                for claim in selected_claims
            ]
        }


class ClaimSelectionTests(unittest.TestCase):
    def client_for(self, runner, *, store=None, executor=None):
        service = AnalysisJobService(
            RunnerStub(),
            article_runner=runner,
            store=store,
            executor=executor or ImmediateExecutor(),
            result_serializer=lambda result: result,
        )
        return create_app(service).test_client(), service

    def start(self, client):
        created = client.post(
            "/api/v1/article-analyses",
            json={"article_reference": "10.1000/example"},
        ).get_json()
        return created, client.get(created["status_url"]).get_json()

    def test_pauses_for_claim_selection_without_leaking_snapshot(self):
        client, _service = self.client_for(PreparingArticleRunnerStub())

        _created, job = self.start(client)

        self.assertEqual(job["status"], "AWAITING_CLAIM_SELECTION")
        self.assertEqual(job["progress"], 40)
        self.assertEqual(
            [claim["claim_id"] for claim in job["result"]["submitted_article"]["claims"]],
            ["claim-01", "claim-02"],
        )
        self.assertIn("whole_article_analysis", job["result"])
        self.assertTrue(job["claim_selection_url"].endswith("/claims"))
        # O snapshot contém o texto integral; ele não deve sair na API pública.
        self.assertNotIn("workflow", job)
        self.assertNotIn("Texto integral do artigo.", str(job))

    def test_status_view_omits_heavy_result(self):
        client, _service = self.client_for(PreparingArticleRunnerStub())
        created, _job = self.start(client)

        light = client.get(created["status_url"] + "?view=status").get_json()

        self.assertEqual(light["status"], "AWAITING_CLAIM_SELECTION")
        self.assertNotIn("result", light)

    def test_researches_only_selected_and_edited_claims(self):
        runner = PreparingArticleRunnerStub()
        client, _service = self.client_for(runner)
        created, job = self.start(client)

        response = client.post(
            job["claim_selection_url"],
            json={
                "claims": [
                    {
                        "claim_id": "claim-02",
                        "text": "  O efeito persistiu por doze meses.  ",
                    }
                ]
            },
        )
        finished = client.get(created["status_url"]).get_json()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["status"], "RESEARCHING")
        self.assertEqual(finished["status"], "SUCCEEDED")
        _prepared, selected = runner.prepared_calls[0]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].claim_id, "claim-02")
        self.assertEqual(selected[0].text, "O efeito persistiu por doze meses.")
        # Texto editado vira a nova consulta; o texto original manteria a consulta extraída.
        self.assertEqual(selected[0].search_query, "O efeito persistiu por doze meses.")

    def test_passes_depth_marks_edits_and_exports_report(self):
        runner = PreparingArticleRunnerStub()
        client, _service = self.client_for(runner)
        created, job = self.start(client)

        client.post(
            job["claim_selection_url"],
            json={
                "claims": [
                    {"claim_id": "claim-01", "text": "O tratamento reduziu a dor em adultos."},
                    {"claim_id": "claim-02", "text": "O efeito persistiu por um ano."},
                ],
                "depth": "DEEP",
            },
        )
        report = client.get(f"/api/v1/analyses/{created['analysis_id']}/report.md")

        selected = tuple(claim for _prepared, claims in runner.prepared_calls for claim in claims)
        self.assertEqual(runner.depths, ["DEEP", "DEEP"])
        self.assertEqual([claim.edited for claim in selected], [False, True])
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.mimetype, "text/markdown")
        self.assertIn("attachment", report.headers["Content-Disposition"])

    def test_rejects_unknown_depth_and_unfinished_export(self):
        client, _service = self.client_for(PreparingArticleRunnerStub())
        created, job = self.start(client)

        response = client.post(
            job["claim_selection_url"],
            json={
                "claims": [{"claim_id": "claim-01", "text": "Texto válido longo."}],
                "depth": "EXHAUSTIVE",
            },
        )
        report = client.get(f"/api/v1/analyses/{created['analysis_id']}/report.md")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(report.status_code, 409)

    def test_keeps_extracted_query_when_text_is_unchanged(self):
        runner = PreparingArticleRunnerStub()
        client, _service = self.client_for(runner)
        _created, job = self.start(client)

        client.post(
            job["claim_selection_url"],
            json={
                "claims": [
                    {
                        "claim_id": "claim-01",
                        "text": "O tratamento reduziu a dor em adultos.",
                    }
                ]
            },
        )

        _prepared, selected = runner.prepared_calls[0]
        self.assertEqual(selected[0].search_query, "treatment pain adults")

    def test_rejects_invalid_selections(self):
        client, _service = self.client_for(PreparingArticleRunnerStub())
        _created, job = self.start(client)
        url = job["claim_selection_url"]

        cases = {
            "empty": {"claims": []},
            "unknown": {"claims": [{"claim_id": "claim-99", "text": "Texto válido longo."}]},
            "duplicate": {
                "claims": [
                    {"claim_id": "claim-01", "text": "Texto válido longo."},
                    {"claim_id": "claim-01", "text": "Texto válido longo."},
                ]
            },
            "short": {"claims": [{"claim_id": "claim-01", "text": "curto"}]},
            "extra_field": {
                "claims": [{"claim_id": "claim-01", "text": "Texto válido longo.", "x": 1}]
            },
            "wrong_shape": {"selected": []},
        }
        for name, payload in cases.items():
            with self.subTest(name):
                self.assertEqual(client.post(url, json=payload).status_code, 422)

        still_waiting = client.get(f"/api/v1/analyses/{job['analysis_id']}").get_json()
        self.assertEqual(still_waiting["status"], "AWAITING_CLAIM_SELECTION")

    def test_rejects_second_selection_after_research_started(self):
        executor = HoldingExecutor()
        client, _service = self.client_for(PreparingArticleRunnerStub(), executor=executor)
        created = client.post(
            "/api/v1/article-analyses",
            json={"article_reference": "10.1000/example"},
        ).get_json()
        function, args, kwargs = executor.submissions.pop()
        function(*args, **kwargs)
        selection = {"claims": [{"claim_id": "claim-01", "text": "Texto válido longo."}]}
        url = f"/api/v1/article-analyses/{created['analysis_id']}/claims"

        first = client.post(url, json=selection)
        second = client.post(url, json=selection)
        pending = client.get(created["status_url"])

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 422)
        self.assertEqual(pending.get_json()["status"], "RESEARCHING")
        self.assertEqual(pending.headers["Retry-After"], "1")

    def test_unknown_analysis_returns_not_found(self):
        client, _service = self.client_for(PreparingArticleRunnerStub())

        response = client.post(
            "/api/v1/article-analyses/unknown/claims",
            json={"claims": [{"claim_id": "claim-01", "text": "Texto válido longo."}]},
        )

        self.assertEqual(response.status_code, 404)


class PreparedArticleSnapshotTests(unittest.TestCase):
    def test_workflow_payload_round_trip(self):
        original = prepared_article()

        restored = PreparedArticle.from_workflow_payload(original.to_workflow_payload())

        self.assertEqual(restored.extracted, original.extracted)
        self.assertEqual(restored.resolved.text, original.resolved.text)
        self.assertEqual(restored.resolved.pages, original.resolved.pages)
        self.assertEqual(restored.resolved.sections, original.resolved.sections)
        self.assertEqual(restored.resolved.authors, original.resolved.authors)
        self.assertEqual(restored.dossier, original.dossier)
        self.assertEqual(restored.whole_article_analysis, original.whole_article_analysis)
        # O conteúdo binário do upload não é persistido.
        self.assertIsNone(restored.submission.content)

    def test_selection_survives_application_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "jobs.sqlite3"
            first_client, _service = ClaimSelectionTests().client_for(
                PreparingArticleRunnerStub(),
                store=SQLiteAnalysisJobStore(database),
            )
            created = first_client.post(
                "/api/v1/article-analyses",
                json={"article_reference": "10.1000/example"},
            ).get_json()

            runner = PreparingArticleRunnerStub()
            second_client, _service = ClaimSelectionTests().client_for(
                runner,
                store=SQLiteAnalysisJobStore(database),
            )
            waiting = second_client.get(created["status_url"]).get_json()
            response = second_client.post(
                waiting["claim_selection_url"],
                json={"claims": [{"claim_id": "claim-01", "text": "Texto válido longo."}]},
            )
            finished = second_client.get(created["status_url"]).get_json()

        self.assertEqual(waiting["status"], "AWAITING_CLAIM_SELECTION")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(finished["status"], "SUCCEEDED")
        prepared, _selected = runner.prepared_calls[0]
        self.assertEqual(prepared.resolved.text, "Texto integral do artigo.")


if __name__ == "__main__":
    unittest.main()
