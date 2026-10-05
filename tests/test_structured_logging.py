import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.structured_logging import (
    bind_log_context,
    close_structured_logging,
    configure_structured_logging,
    logged_step,
)


class StructuredLoggingTests(unittest.TestCase):
    def test_writes_correlated_step_as_json_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.jsonl"
            configure_structured_logging(
                level="INFO", log_file=path, enable_stdout=False
            )
            logger = logging.getLogger("fatofake.tests")

            with bind_log_context(request_id="req-1", analysis_id="analysis-1"):
                with logged_step(logger, "controlled_stage") as details:
                    details["candidate_count"] = 3

            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            close_structured_logging()

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["status"], "started")
        self.assertEqual(records[1]["status"], "completed")
        self.assertEqual(records[1]["stage"], "controlled_stage")
        self.assertEqual(records[1]["analysis_id"], "analysis-1")
        self.assertEqual(records[1]["request_id"], "req-1")
        self.assertEqual(records[1]["candidate_count"], 3)
        self.assertGreaterEqual(records[1]["duration_ms"], 0)

    def test_records_failed_step_without_swallowing_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.jsonl"
            configure_structured_logging(
                level="INFO", log_file=path, enable_stdout=False
            )
            logger = logging.getLogger("fatofake.tests")

            with self.assertRaisesRegex(ValueError, "controlled"):
                with logged_step(logger, "failure_stage"):
                    raise ValueError("controlled")

            record = json.loads(
                path.read_text(encoding="utf-8").splitlines()[-1]
            )
            close_structured_logging()

        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error_type"], "ValueError")
        self.assertIn("ValueError: controlled", record["exception"])


if __name__ == "__main__":
    unittest.main()
