from __future__ import annotations

import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
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
            patch.object(client, "_request_now", side_effect=timeout_request),
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
                with patch.object(client, "_request_now", side_effect=error) as request:
                    with self.assertRaises(WorkIqError) as caught:
                        client.start()
                self.assertIs(caught.exception, error)
                request.assert_called_once()
                self.assertEqual(client.timeout, 20)
                self.assertIsNone(client._process)

    def test_tool_timeout_is_not_retried(self):
        with WorkIqMcpClient(command=self.command(), timeout=5) as client:
            client.timeout = 0.01
            with patch.object(client, "_send") as send:
                with self.assertRaises(WorkIqError) as caught:
                    client.call_tool("ask", {"question": "Ready?"})
        self.assertEqual(caught.exception.code, "mcp_timeout")
        self.assertIn("startup", caught.exception.remedy)
        send.assert_called_once()

    def wait_for_pending(self, client, count):
        with client._condition:
            self.assertTrue(client._condition.wait_for(
                lambda: len(client._pending_requests) == count, timeout=2
            ))

    def test_requests_before_start_wait_and_run_in_fifo_order(self):
        client = WorkIqMcpClient(
            command=[*self.command(), "--drop-first-initialize"],
            timeout=5,
        )
        self.addCleanup(client.close)
        with (
            patch("amplifier_smart_tool_workiq.client._INITIALIZE_RETRY_TIMEOUT", 0.1),
            patch.object(client, "_send", wraps=client._send) as send,
            ThreadPoolExecutor(max_workers=3) as pool,
        ):
            futures = []
            for index in range(3):
                futures.append(pool.submit(
                    client.call_tool, "ask", {"question": str(index)}
                ))
                self.wait_for_pending(client, index + 1)
            send.assert_not_called()
            client.start()
            results = [future.result(timeout=5) for future in futures]

        self.assertEqual(
            [result["response"] for result in results],
            ["Answer to: 0", "Answer to: 1", "Answer to: 2"],
        )
        messages = [call.args[0] for call in send.call_args_list]
        self.assertEqual(
            [message["params"]["arguments"]["question"] for message in messages
             if message["method"] == "tools/call"],
            ["0", "1", "2"],
        )
        methods = [message["method"] for message in messages]
        self.assertLess(
            methods.index("notifications/initialized"), methods.index("tools/call")
        )
        self.assertFalse(client._pending_requests)

    def test_requests_and_concurrent_start_wait_for_handshake(self):
        client = WorkIqMcpClient(command=self.command(), timeout=5)
        self.addCleanup(client.close)
        initializing = threading.Event()
        release = threading.Event()
        initialize = client._initialize

        def delayed_initialize():
            initializing.set()
            self.assertTrue(release.wait(5))
            initialize()

        with (
            patch.object(client, "_initialize", side_effect=delayed_initialize),
            patch.object(client, "_send", wraps=client._send) as send,
            ThreadPoolExecutor(max_workers=3) as pool,
        ):
            first_start = pool.submit(client.start)
            try:
                self.assertTrue(initializing.wait(2))
                second_start = pool.submit(client.start)
                tools = pool.submit(client.list_tools)
                self.wait_for_pending(client, 1)
                self.assertFalse(second_start.done())
                send.assert_not_called()
            finally:
                release.set()
            first_start.result(timeout=5)
            second_start.result(timeout=5)
            self.assertEqual(tools.result(timeout=5)[0]["name"], "ask")

    def test_startup_failure_releases_all_queued_requests(self):
        client = WorkIqMcpClient(command=self.command(), timeout=5)
        error = WorkIqError("mcp_start_failed", "Cannot start", "Check setup.")
        with (
            patch.object(client, "_start_process", side_effect=error) as start,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            futures = [pool.submit(client.list_tools) for _ in range(2)]
            self.wait_for_pending(client, 2)
            with self.assertRaises(WorkIqError):
                client.start()
            for future in futures:
                with self.assertRaises(WorkIqError) as caught:
                    future.result(timeout=2)
                self.assertEqual(caught.exception.code, "mcp_start_failed")
            start.assert_called_once()
        self.assertFalse(client._pending_requests)
        self.assertIsNone(client._process)

    def test_close_releases_queued_requests_without_sending(self):
        client = WorkIqMcpClient(command=self.command(), timeout=5)
        with (
            patch.object(client, "_send") as send,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            futures = [pool.submit(client.list_tools) for _ in range(2)]
            self.wait_for_pending(client, 2)
            client.close()
            for future in futures:
                with self.assertRaises(WorkIqError) as caught:
                    future.result(timeout=2)
                self.assertEqual(caught.exception.code, "mcp_closed")
            send.assert_not_called()
        self.assertFalse(client._pending_requests)

    def test_queue_timeout_removes_unsent_request(self):
        client = WorkIqMcpClient(command=self.command(), timeout=0.01)
        with patch.object(client, "_send") as send:
            with self.assertRaises(WorkIqError) as caught:
                client.list_tools()
            send.assert_not_called()
        self.assertEqual(caught.exception.code, "mcp_queue_timeout")
        self.assertFalse(client._pending_requests)

    def test_close_then_restart_uses_a_fresh_response_queue(self):
        client = WorkIqMcpClient(command=self.command(), timeout=5)
        for _ in range(2):
            with client:
                self.assertEqual(client.list_tools()[0]["name"], "ask")

    def test_close_waits_for_active_request_and_cancels_pending(self):
        with WorkIqMcpClient(command=self.command(), timeout=5) as client:
            active = threading.Event()
            release = threading.Event()
            request_now = client._request_now

            def delayed_request(method, params):
                active.set()
                self.assertTrue(release.wait(5))
                return request_now(method, params)

            with (
                patch.object(client, "_request_now", side_effect=delayed_request),
                ThreadPoolExecutor(max_workers=3) as pool,
            ):
                first = pool.submit(client.list_tools)
                try:
                    self.assertTrue(active.wait(2))
                    second = pool.submit(client.list_tools)
                    self.wait_for_pending(client, 2)
                    closing = pool.submit(client.close)
                    with self.assertRaises(WorkIqError) as caught:
                        second.result(timeout=2)
                    self.assertEqual(caught.exception.code, "mcp_closed")
                    self.assertFalse(closing.done())
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=5)[0]["name"], "ask")
                closing.result(timeout=5)
            self.assertFalse(client._pending_requests)
            self.assertIsNone(client._process)

    def test_transport_failure_releases_pending_without_resending(self):
        with WorkIqMcpClient(command=self.command(), timeout=5) as client:
            active = threading.Event()
            release = threading.Event()
            error = WorkIqError("mcp_exited", "Server exited", "Restart.")

            def failed_request(method, params):
                active.set()
                self.assertTrue(release.wait(5))
                raise error

            with (
                patch.object(client, "_request_now", side_effect=failed_request) as request,
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                first = pool.submit(client.list_tools)
                try:
                    self.assertTrue(active.wait(2))
                    second = pool.submit(client.list_tools)
                    self.wait_for_pending(client, 2)
                finally:
                    release.set()
                for future in (first, second):
                    with self.assertRaises(WorkIqError) as caught:
                        future.result(timeout=2)
                    self.assertEqual(caught.exception.code, "mcp_exited")
                request.assert_called_once()
            self.assertFalse(client._pending_requests)


if __name__ == "__main__":
    unittest.main()
