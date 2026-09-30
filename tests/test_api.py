import sys
import unittest
from concurrent.futures import Future
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.api import AnalysisJobService, create_app


class ImmediateExecutor:
    def submit(self, function, *args, **kwargs):
        future = Future()
        try:
            future.set_result(function(*args, **kwargs))
        except Exception as error:
            future.set_exception(error)
        return future

    def shutdown(self, wait=True):
        return None


class HoldingExecutor:
    def __init__(self):
        self.submissions = []

    def submit(self, function, *args, **kwargs):
        self.submissions.append((function, args, kwargs))
        return Future()

    def shutdown(self, wait=True):
        return None


class RunnerStub:
    def __init__(self, result=None, error=None):
        self.result = result or {"report": {"conclusion": "INCONCLUSIVE"}}
        self.error = error
        self.calls = []

    def analyze(self, claim, article_reference=None):
        self.calls.append((claim, article_reference))
        if self.error:
            raise self.error
        return self.result


class ArticleRunnerStub:
    def __init__(self):
        self.submissions = []

    def analyze_article(self, submission):
        self.submissions.append(submission)
        return {"submitted_article": {"primary_claim": "Extracted claim."}}


class ApiTests(unittest.TestCase):
    def app_for(self, runner):
        service = AnalysisJobService(
            runner,
            executor=ImmediateExecutor(),
            result_serializer=lambda result: result,
        )
        return create_app(service), service

    def test_health_endpoint(self):
        app, _service = self.app_for(RunnerStub())
        response = app.test_client().get("/api/v1/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_serves_the_user_acceptance_page(self):
        app, _service = self.app_for(RunnerStub())

        response = app.test_client().get("/")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Qual artigo você quer verificar?", page)
        self.assertIn("/api/v1/article-analyses", page)
        self.assertIn("Imagem ou arquivo do artigo", page)
        self.assertIn("não oferece diagnóstico", page)
        self.assertIn("Resposta em linguagem clara", page)
        self.assertIn("Alegações identificadas no artigo", page)
        self.assertIn("O que conseguimos ler", page)
        self.assertIn("Evidências independentes encontradas", page)
        self.assertIn("Ver detalhes técnicos e alertas", page)

    def test_creates_job_and_returns_completed_result(self):
        runner = RunnerStub()
        app, _service = self.app_for(runner)
        client = app.test_client()

        created = client.post(
            "/api/v1/analyses",
            json={
                "claim": "  Beber café pode alterar o risco de câncer.  ",
                "article_reference": "doi:10.1000/example",
            },
        )
        created_payload = created.get_json()
        fetched = client.get(created_payload["status_url"])
        fetched_payload = fetched.get_json()

        self.assertEqual(created.status_code, 202)
        self.assertEqual(created_payload["status"], "QUEUED")
        self.assertEqual(created.headers["Location"], created_payload["status_url"])
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched_payload["status"], "SUCCEEDED")
        self.assertEqual(fetched_payload["progress"], 100)
        self.assertEqual(
            fetched_payload["result"]["report"]["conclusion"],
            "INCONCLUSIVE",
        )
        self.assertEqual(
            runner.calls,
            [("Beber café pode alterar o risco de câncer.", "10.1000/example")],
        )

    def test_creates_article_first_job_from_a_link(self):
        article_runner = ArticleRunnerStub()
        service = AnalysisJobService(
            RunnerStub(),
            article_runner=article_runner,
            executor=ImmediateExecutor(),
            result_serializer=lambda result: result,
        )
        client = create_app(service).test_client()

        created = client.post(
            "/api/v1/article-analyses",
            json={"article_reference": "https://doi.org/10.1000/example"},
        )
        fetched = client.get(created.get_json()["status_url"]).get_json()

        self.assertEqual(created.status_code, 202)
        self.assertEqual(fetched["status"], "SUCCEEDED")
        self.assertEqual(
            fetched["result"]["submitted_article"]["primary_claim"],
            "Extracted claim.",
        )
        self.assertEqual(article_runner.submissions[0].reference, "10.1000/example")

    def test_article_endpoint_requires_exactly_one_source(self):
        article_runner = ArticleRunnerStub()
        service = AnalysisJobService(
            RunnerStub(),
            article_runner=article_runner,
            executor=ImmediateExecutor(),
        )
        client = create_app(service).test_client()

        missing = client.post("/api/v1/article-analyses", json={})
        duplicate = client.post(
            "/api/v1/article-analyses",
            json={
                "article_reference": "10.1000/example",
                "article_file": {
                    "name": "article.pdf",
                    "mime_type": "application/pdf",
                    "data_base64": "JVBERg==",
                },
            },
        )

        self.assertEqual(missing.status_code, 422)
        self.assertEqual(duplicate.status_code, 422)

    def test_rejects_invalid_requests(self):
        app, _service = self.app_for(RunnerStub())
        client = app.test_client()

        not_json = client.post("/api/v1/analyses", data="claim=x")
        short_claim = client.post("/api/v1/analyses", json={"claim": "curta"})
        unknown = client.post(
            "/api/v1/analyses",
            json={"claim": "Alegação válida para análise.", "extra": True},
        )

        self.assertEqual(not_json.status_code, 415)
        self.assertEqual(short_claim.status_code, 422)
        self.assertEqual(unknown.status_code, 400)

    def test_returns_not_found_for_unknown_job(self):
        app, _service = self.app_for(RunnerStub())
        response = app.test_client().get("/api/v1/analyses/unknown")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "ANALYSIS_NOT_FOUND")

    def test_sets_retry_after_while_job_is_pending(self):
        executor = HoldingExecutor()
        service = AnalysisJobService(
            RunnerStub(),
            executor=executor,
            result_serializer=lambda result: result,
        )
        client = create_app(service).test_client()
        created = client.post(
            "/api/v1/analyses",
            json={"claim": "Alegação válida para análise científica."},
        ).get_json()

        response = client.get(created["status_url"])

        self.assertEqual(response.get_json()["status"], "QUEUED")
        self.assertEqual(response.headers["Retry-After"], "1")
        self.assertEqual(len(executor.submissions), 1)

    def test_hides_unexpected_internal_error(self):
        runner = RunnerStub(error=RuntimeError("token-secreto"))
        app, _service = self.app_for(runner)
        client = app.test_client()

        created = client.post(
            "/api/v1/analyses",
            json={"claim": "Alegação válida para análise científica."},
        ).get_json()
        fetched = client.get(created["status_url"])
        payload = fetched.get_json()

        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["error"]["code"], "INTERNAL_ANALYSIS_ERROR")
        self.assertNotIn("token-secreto", str(payload))


if __name__ == "__main__":
    unittest.main()
