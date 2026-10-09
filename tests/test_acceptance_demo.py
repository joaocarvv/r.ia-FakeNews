import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import AnalysisServiceError
from fatofake.acceptance_demo import AcceptanceDemoRunner, create_acceptance_demo_app


class AcceptanceDemoTests(unittest.TestCase):
    def test_demo_contract_is_explicitly_synthetic(self):
        result = AcceptanceDemoRunner(delay=0).analyze(
            "O consumo de café aumenta o risco de câncer de próstata."
        )

        self.assertEqual(result["report"]["conclusion"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("sintético", result["report"]["summary"])
        self.assertTrue(
            all("não científica" in source["label"] for source in result["report"]["sources"])
        )
        self.assertEqual(len(result["articles"]), 2)

    def test_demo_rejects_claim_outside_its_controlled_topic(self):
        with self.assertRaises(AnalysisServiceError):
            AcceptanceDemoRunner(delay=0).analyze(
                "A vitamina C evita todas as infecções respiratórias."
            )

    def test_page_submits_and_returns_a_complete_demo_result(self):
        app = create_acceptance_demo_app(delay=0)
        client = app.test_client()
        created = client.post(
            "/api/v1/analyses",
            json={
                "claim": "O consumo de café aumenta o risco de câncer de próstata.",
                "article_reference": None,
            },
        )
        payload = created.get_json()

        completed = None
        for _ in range(50):
            completed = client.get(payload["status_url"]).get_json()
            if completed["status"] in {"SUCCEEDED", "FAILED"}:
                break
            time.sleep(0.01)

        self.assertEqual(created.status_code, 202)
        self.assertEqual(completed["status"], "SUCCEEDED")
        self.assertEqual(completed["result"]["synthesis"]["article_count"], 2)
        self.assertEqual(len(completed["result"]["report"]["limitations"]), 3)
        app.extensions["fatofake_job_service"].close()


if __name__ == "__main__":
    unittest.main()
