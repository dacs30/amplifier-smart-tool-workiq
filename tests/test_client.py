from __future__ import annotations

import sys
import unittest
from pathlib import Path

from amplifier_smart_tool_workiq.client import WorkIqMcpClient
from amplifier_smart_tool_workiq.errors import WorkIqError


class WorkIqMcpClientTests(unittest.TestCase):
    def command(self) -> list[str]:
        server = Path(__file__).with_name("fake_mcp_server.py")
        return [sys.executable, str(server)]

    def test_lists_tools_and_parses_text_content(self):
        with WorkIqMcpClient(command=self.command(), timeout=5) as client:
            names = [tool["name"] for tool in client.list_tools()]
            result = client.call_tool("ask", {"question": "What changed?"})

        self.assertEqual(names, ["ask", "fetch"])
        self.assertEqual(result["conversationId"], "conversation-1")
        self.assertEqual(result["response"], "Answer to: What changed?")

    def test_returns_structured_content(self):
        with WorkIqMcpClient(command=self.command(), timeout=5) as client:
            result = client.call_tool(
                "fetch",
                {
                    "entityUrls": [
                        "/me/messages?$select=id,subject&$top=1"
                    ]
                },
            )

        self.assertEqual(result["results"][0]["statusCode"], 200)
        self.assertEqual(
            result["results"][0]["data"]["value"][0]["subject"],
            "Example",
        )

    def test_maps_eula_failure_to_actionable_error(self):
        error = WorkIqMcpClient._tool_error(
            "You must accept the End User License Agreement. "
            "Use the accept_eula tool."
        )
        self.assertEqual(error.code, "eula_required")
        self.assertIn("accept-eula --yes", error.remedy)
        self.assertTrue(error.details["requires_confirmation"])
        self.assertEqual(
            error.details["terms_url"],
            "https://github.com/microsoft/work-iq",
        )
        self.assertEqual(
            error.details["action"],
            {"capability": "accept-eula", "arguments": ["--yes"]},
        )

    def test_failed_initialization_closes_process(self):
        client = WorkIqMcpClient(
            command=[*self.command(), "--hang"],
            timeout=0.1,
        )

        with self.assertRaises(WorkIqError):
            client.start()

        self.assertIsNone(client._process)


if __name__ == "__main__":
    unittest.main()
