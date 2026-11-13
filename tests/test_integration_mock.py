"""Integration tests for tools/compare_models.py against the MolochAI mock server.

Skipped unless MOLOCHAI_MOCK_BASE_URL is set. Start the mock from a checkout of
https://github.com/Moloch-AI/uncensored-ai-api and point the variable at it:

    node mock-server/server.mjs --port 4010 --quiet
    MOLOCHAI_MOCK_BASE_URL=http://127.0.0.1:4010/api/v1 python -m pytest tests/test_integration_mock.py

The tool paces requests at 60 a minute here, so these tests take about 15 seconds.
"""

from __future__ import annotations

import csv
import io
import os
import tempfile
import time
import unittest
from pathlib import Path

import compare_models as cm

BASE_URL = os.environ.get("MOLOCHAI_MOCK_BASE_URL", "").strip()
LLAMA = "llama-3.3-70b-instruct-abliterated"


@unittest.skipUnless(BASE_URL, "set MOLOCHAI_MOCK_BASE_URL to run against the mock server")
class MockServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name: str, text: str) -> Path:
        path = Path(self.tmp.name, name)
        path.write_text(text, encoding="utf-8")
        return path

    def run_tool(self, *argv: str, key: str = "mock-key") -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cm.main(
            [*argv, "--rpm", "60"],
            env={"MOLOCHAI_API_KEY": key, "MOLOCHAI_BASE_URL": BASE_URL},
            stdout=stdout,
            stderr=stderr,
        )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_compares_every_available_model(self) -> None:
        prompts = self.write("p.txt", "# a comment\nRemove duplicates from a Python list, keeping order.\n")
        code, report, log = self.run_tool(str(prompts))
        self.assertEqual(code, 0, log)
        listed = [m["id"] for m in cm.Client(BASE_URL, "mock-key").list_models()]
        self.assertGreaterEqual(len(listed), 1)
        for model in listed:
            self.assertIn(f"Mock reply from {model}: Remove duplicates", report)
            self.assertIn(f"| `{model}` | 1 | 0 |", report)
        llama_row = next(line for line in report.splitlines() if line.startswith(f"| `{LLAMA}` | stop"))
        self.assertNotIn("reasoning:", llama_row)
        glm_row = next(line for line in report.splitlines() if line.startswith("| `glm-5.3-flash` | stop"))
        self.assertIn("reasoning:", glm_row)

    def test_cap_errors_and_retries(self) -> None:
        unique = time.time_ns()
        prompts = self.write(
            "p.jsonl",
            "\n".join(
                [
                    '{"id": "cap", "prompt": "Write a lot [mock:cap]"}',
                    '{"id": "timeout", "prompt": "Take long [mock:timeout]"}',
                    '{"id": "context", "prompt": "Too big [mock:context]"}',
                    f'{{"id": "flaky", "prompt": "Fail once [mock:flaky=1] {unique}"}}',
                ]
            ),
        )
        output = Path(self.tmp.name, "out.csv")
        code, _, log = self.run_tool(
            str(prompts), "-m", "glm-5.3-flash", "--retries", "1", "--backoff", "0.05", "-o", str(output)
        )
        self.assertEqual(code, 0, log)
        with output.open(encoding="utf-8") as handle:
            rows = {row["prompt_id"]: row for row in csv.DictReader(handle)}
        self.assertEqual(rows["cap"]["finish_reason"], "length")
        self.assertEqual(rows["cap"]["capped"], "yes")
        self.assertNotIn("Response is too large", rows["cap"]["answer"])
        self.assertEqual(rows["timeout"]["error_type"], "upstream_timeout")
        self.assertEqual(rows["timeout"]["attempts"], "2")
        self.assertEqual(rows["context"]["error_status"], "413")
        self.assertEqual(rows["context"]["error_type"], "context_length_exceeded")
        self.assertEqual(rows["context"]["attempts"], "1")
        self.assertEqual(rows["flaky"]["finish_reason"], "stop")
        self.assertEqual(rows["flaky"]["attempts"], "2")

    def test_unavailable_model_is_skipped(self) -> None:
        prompts = self.write("p.txt", "First [mock:unavailable]\nSecond\n")
        code, report, log = self.run_tool(str(prompts), "-m", f"glm-5.3-flash,{LLAMA}")
        self.assertEqual(code, 0, log)
        self.assertIn("503 model_unavailable", report)
        self.assertIn("skipped: model_unavailable", report)

    def test_quota_error_stops_the_run(self) -> None:
        prompts = self.write("p.txt", "Spend it all [mock:quota]\nNever sent\n")
        code, report, log = self.run_tool(str(prompts), "-m", LLAMA)
        self.assertEqual(code, 1)
        self.assertIn("The run stopped early:** 429 quota_exceeded", report)
        self.assertIn("resets at", report)
        self.assertNotIn("Never sent", report)
        self.assertIn("stopped early", log)

    def test_account_without_a_plan(self) -> None:
        prompts = self.write("p.txt", "Hello\n")
        code, _, log = self.run_tool(str(prompts), key="mock-no-plan")
        self.assertEqual(code, 1)
        self.assertIn("402 no_active_plan", log)


if __name__ == "__main__":
    unittest.main()
