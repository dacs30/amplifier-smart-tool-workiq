from __future__ import annotations

import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from amplifier_smart_tool_workiq import cli


class CliTests(unittest.TestCase):
    @classmethod
    def cli(cls) -> Path:
        return (
            Path(__file__).parents[1]
            / "src"
            / "amplifier_smart_tool_workiq"
            / "cli.py"
        )

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.cli()), *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )

    def test_doctor_is_deterministic(self):
        completed = self.run_cli("doctor", "--local-only")
        document = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(document["capability"], "doctor")
        self.assertEqual(document["kind"], "deterministic")

    def test_doctor_recommends_global_workiq_for_npx_fallback(self):
        paths = {
            "workiq": None,
            "npx": "C:\\Program Files\\nodejs\\npx.cmd",
            "node": "C:\\Program Files\\nodejs\\node.exe",
        }
        output = StringIO()

        with (
            patch.object(cli.shutil, "which", side_effect=paths.get),
            redirect_stdout(output),
        ):
            exit_code = cli._doctor(SimpleNamespace(local_only=True))

        document = json.loads(output.getvalue())
        workiq = document["result"]["checks"]["workiq"]
        self.assertEqual(exit_code, 0)
        self.assertEqual(workiq["launcher"], "npx fallback")
        self.assertIn("npm install -g @microsoft/workiq", workiq["note"])

    def test_bad_invocation_is_nonzero_json(self):
        completed = self.run_cli("__not_a_capability__")
        document = json.loads(completed.stdout)

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(document["error"]["code"], "bad_invocation")

    def test_eula_requires_explicit_confirmation(self):
        completed = self.run_cli("accept-eula")
        document = json.loads(completed.stdout)

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(document["error"]["code"], "confirmation_required")

    def test_workflow_requires_a_subcommand(self):
        completed = self.run_cli("workflow")
        document = json.loads(completed.stdout)

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(document["error"]["code"], "no_capability")


if __name__ == "__main__":
    unittest.main()
