from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch

from amplifier_smart_tool_workiq.command import run_workiq


class CommandTests(unittest.TestCase):
    def test_interactive_output_is_redirected_away_from_stdout(self):
        child = [
            sys.executable,
            "-c",
            (
                "import sys; "
                "print('interactive stdout'); "
                "print('interactive stderr', file=sys.stderr)"
            ),
        ]
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
            with patch(
                "amplifier_smart_tool_workiq.command.workiq_command",
                return_value=child,
            ):
                with patch.object(sys, "stderr", stderr):
                    completed = run_workiq([], timeout=5, interactive=True)
            stderr.seek(0)
            diagnostics = stderr.read()

        self.assertEqual(completed.returncode, 0)
        self.assertIn("interactive stdout", diagnostics)
        self.assertIn("interactive stderr", diagnostics)
        self.assertIsNone(completed.stdout)


if __name__ == "__main__":
    unittest.main()
