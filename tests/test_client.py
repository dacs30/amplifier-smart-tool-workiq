from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

        self.assertEqual(
            names,
            ["ask", "fetch", "search_paths", "get_schema"],
        )
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

        with self.assertRaises(WorkIqError) as caught:
            client.start()

        self.assertEqual(caught.exception.code, "mcp_timeout")
        self.assertTrue(caught.exception.retryable)
        self.assertIn("0.1 seconds", caught.exception.message)
        self.assertIn("startup", caught.exception.remedy)
        self.assertEqual(client.timeout, 0.1)
        self.assertIsNone(client._process)

    def test_retries_dropped_initialize_and_ignores_late_response(self):
        with patch(
            "amplifier_smart_tool_workiq.client._INITIALIZE_RETRY_TIMEOUT", 0.1
        ):
            with WorkIqMcpClient(
                command=[
                    *self.command(),
                    "--drop-first-initialize",
                    "--late-initialize-response",
                ],
                timeout=5,
            ) as client:
                self.assertGreaterEqual(client._next_id, 3)
                self.assertEqual(client.timeout, 5)
                self.assertEqual(client.list_tools()[0]["name"], "ask")
                self.assertEqual(
                    client.call_tool("ask", {"question": "Ready?"})["response"],
                    "Answer to: Ready?",
                )

    def test_initialize_retries_within_overall_timeout(self):
        client = WorkIqMcpClient(command=self.command(), timeout=20)
        now = 100.0
        budgets = []

        def timeout_request(method, params, *, timeout):
            nonlocal now
            self.assertEqual(method, "initialize")
            budgets.append(timeout)
            now += timeout
            raise WorkIqError("mcp_timeout", "No response", "Retry.")

        with (
            patch(
                "amplifier_smart_tool_workiq.client.time.monotonic",
                side_effect=lambda: now,
            ),
            patch.object(client, "_request", side_effect=timeout_request),
        ):
            with self.assertRaises(WorkIqError) as caught:
                client._initialize()

        self.assertEqual(budgets, [8, 8, 4])
        self.assertEqual(client.timeout, 20)
        self.assertEqual(caught.exception.code, "mcp_timeout")
        self.assertIn("20 seconds", caught.exception.message)

    def test_initialize_does_not_retry_other_errors(self):
        for code in ("mcp_exited", "authentication_required", "invalid_mcp_response"):
            with self.subTest(code=code):
                client = WorkIqMcpClient(command=self.command(), timeout=20)
                error = WorkIqError(code, "Initialization failed", "Check setup.")
                with patch.object(client, "_request", side_effect=error) as request:
                    with self.assertRaises(WorkIqError) as caught:
                        client.start()
                self.assertIs(caught.exception, error)
                request.assert_called_once()
                self.assertEqual(client.timeout, 20)
                self.assertIsNone(client._process)

    def test_tool_timeout_is_not_retried(self):
        client = WorkIqMcpClient(command=self.command(), timeout=0.01)
        with patch.object(client, "_send") as send:
            with self.assertRaises(WorkIqError) as caught:
                client.call_tool("ask", {"question": "Ready?"})
        self.assertEqual(caught.exception.code, "mcp_timeout")
        self.assertIn("startup", caught.exception.remedy)
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
