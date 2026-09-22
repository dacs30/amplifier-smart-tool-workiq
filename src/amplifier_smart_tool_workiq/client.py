"""Minimal synchronous MCP stdio client for the official Work IQ server."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections import deque
from collections.abc import Sequence
from typing import Any

from .command import workiq_command
from .errors import WorkIqError, sanitize

_PROTOCOL_VERSION = "2025-06-18"
_INITIALIZE_RETRY_TIMEOUT = 8.0
_STOP = object()


class WorkIqMcpClient:
    """Manage one Work IQ MCP server process and JSON-RPC session."""

    def __init__(
        self,
        *,
        account: str | None = None,
        timeout: float = 120,
        command: Sequence[str] | None = None,
    ):
        self.account = account
        self.timeout = timeout
        self.command = list(command) if command else workiq_command()
        self._process: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[dict[str, Any] | object] = queue.Queue()
        self._stderr: list[str] = []
        self._threads: list[threading.Thread] = []
        self._next_id = 1
        self._condition = threading.Condition()
        self._pending_requests: deque[object] = deque()
        self._ready = False
        self._starting = False
        self._closing = False
        self._closed = False
        self._active_request = False
        self._generation = 0
        self._session_error: WorkIqError | None = None

    def __enter__(self) -> "WorkIqMcpClient":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(self) -> None:
        with self._condition:
            self._condition.wait_for(
                lambda: not self._closing and not self._active_request
            )
            if self._starting:
                self._condition.wait_for(lambda: not self._starting)
                if self._session_error:
                    raise self._session_error
                if self._closed:
                    raise self._closed_error()
            if self._ready:
                return
            if self._session_error:
                self._generation += 1
            self._starting = True
            self._closed = False
            self._session_error = None

        try:
            self._close_process()
            self._messages = queue.Queue()
            self._stderr = []
            self._start_process()
            with self._condition:
                if self._closed:
                    raise self._closed_error()
        except BaseException as error:
            with self._condition:
                self._session_error = (
                    error if isinstance(error, WorkIqError) else WorkIqError(
                        "mcp_start_failed",
                        "Work IQ MCP startup was interrupted.",
                        "Call start() to retry initialization.",
                    )
                )
                self._condition.notify_all()
            self._close_process()
            raise
        else:
            with self._condition:
                self._ready = not self._closing
        finally:
            with self._condition:
                self._starting = False
                self._condition.notify_all()

    def _start_process(self) -> None:
        arguments = [*self.command, "mcp", "--log-level", "Error"]
        if self.account:
            arguments.extend(["--account", self.account])

        try:
            self._process = subprocess.Popen(
                arguments,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as error:
            raise WorkIqError(
                "mcp_start_failed",
                sanitize(str(error)),
                "Run 'workiq-smart-tool doctor' and install the missing "
                "prerequisite.",
            ) from error

        self._threads = [
            threading.Thread(target=self._read_stdout, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for thread in self._threads:
            thread.start()

        self._initialize()
        self._notify("notifications/initialized", {})

    def _initialize(self) -> None:
        params = {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "amplifier-smart-tool-workiq",
                "version": "0.3.0",
            },
        }
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._timeout_error("initialize")
            try:
                # Work IQ can drop stdin before its startup reader attaches.
                self._request_now(
                    "initialize",
                    params,
                    timeout=min(_INITIALIZE_RETRY_TIMEOUT, remaining),
                )
                return
            except WorkIqError as error:
                if error.code != "mcp_timeout":
                    raise

    def close(self) -> None:
        with self._condition:
            if self._closing:
                self._condition.wait_for(lambda: not self._closing)
                return
            self._closing = True
            self._closed = True
            self._ready = False
            self._generation += 1
            self._condition.notify_all()
            self._condition.wait_for(
                lambda: not self._starting and not self._active_request
            )
        try:
            self._close_process()
        finally:
            with self._condition:
                self._closing = False
                self._condition.notify_all()

    def _close_process(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return

        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for thread in self._threads:
            thread.join(timeout=1)
        self._threads = []
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise WorkIqError(
                "invalid_mcp_response",
                "Work IQ returned a tools/list response without a tools array.",
                "Update @microsoft/workiq and retry.",
            )
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        if result.get("isError"):
            message = self._content_text(result) or "Work IQ rejected the request."
            raise self._tool_error(message)

        if "structuredContent" in result:
            return result["structuredContent"]

        text = self._content_text(result)
        if text is None:
            return result
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        ticket = object()
        deadline = time.monotonic() + self.timeout
        with self._condition:
            generation = self._generation
            self._pending_requests.append(ticket)
            self._condition.notify_all()
            try:
                while True:
                    if self._closed or generation != self._generation:
                        raise self._closed_error()
                    if self._session_error:
                        raise self._session_error
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise WorkIqError(
                            "mcp_queue_timeout",
                            f"Work IQ MCP request '{method}' waited more than "
                            f"{self.timeout:g} seconds for a ready session.",
                            "Call start() or use a context manager, and increase "
                            "--timeout if startup or queued requests are slow.",
                            retryable=True,
                        )
                    if (
                        self._ready
                        and not self._active_request
                        and self._pending_requests[0] is ticket
                    ):
                        self._active_request = True
                        break
                    self._condition.wait(timeout=remaining)
            except BaseException:
                self._pending_requests.remove(ticket)
                self._condition.notify_all()
                raise

        try:
            return self._request_now(method, params)
        except WorkIqError as error:
            if error.code in ("mcp_exited", "mcp_write_failed"):
                with self._condition:
                    self._ready = False
                    self._session_error = error
            raise
        finally:
            with self._condition:
                self._active_request = False
                self._pending_requests.remove(ticket)
                self._condition.notify_all()

    @staticmethod
    def _closed_error() -> WorkIqError:
        return WorkIqError(
            "mcp_closed",
            "The Work IQ MCP session was closed before the request could run.",
            "Call start() before submitting new requests.",
        )

    def _request_now(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )

        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._timeout_error(method)
            try:
                message = self._messages.get(timeout=remaining)
            except queue.Empty as error:
                raise self._timeout_error(method) from error

            if message is _STOP:
                raise WorkIqError(
                    "mcp_exited",
                    self._stderr_detail("Work IQ MCP exited unexpectedly."),
                    "Run 'workiq-smart-tool authenticate', then retry. Use "
                    "'doctor' to check local prerequisites.",
                )
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                detail = error.get("message", str(error))
                raise self._tool_error(detail)
            result = message.get("result")
            if not isinstance(result, dict):
                raise WorkIqError(
                    "invalid_mcp_response",
                    f"Work IQ returned an invalid result for '{method}'.",
                    "Update @microsoft/workiq and retry.",
                )
            return result

    def _timeout_error(self, method: str) -> WorkIqError:
        return WorkIqError(
            "mcp_timeout",
            f"Work IQ MCP did not answer '{method}' within "
            f"{self.timeout:g} seconds.",
            "Retry or increase --timeout to allow for Work IQ startup or a "
            "slow response. Run 'workiq-smart-tool doctor' to check local "
            "prerequisites; authenticate only if sign-in is required.",
            retryable=True,
        )

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _send(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise WorkIqError(
                "mcp_not_started",
                "The Work IQ MCP process is not running.",
                "Create the client with a context manager or call start().",
            )
        try:
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise WorkIqError(
                "mcp_write_failed",
                self._stderr_detail(str(error)),
                "Run 'workiq-smart-tool authenticate', then retry.",
            ) from error

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                message = json.loads(stripped)
            except json.JSONDecodeError:
                self._stderr.append(f"Unexpected MCP output: {stripped}")
                continue
            if isinstance(message, dict):
                self._messages.put(message)
        self._messages.put(_STOP)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            stripped = sanitize(line.strip())
            if stripped:
                self._stderr.append(stripped)
                del self._stderr[:-20]

    @staticmethod
    def _content_text(result: dict[str, Any]) -> str | None:
        content = result.get("content")
        if not isinstance(content, list):
            return None
        texts = [
            item["text"]
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]
        return "\n".join(texts) if texts else None

    def _stderr_detail(self, fallback: str) -> str:
        return sanitize("\n".join(self._stderr[-5:]) or fallback)

    @staticmethod
    def _tool_error(message: str) -> WorkIqError:
        safe = sanitize(message)
        lowered = safe.lower()
        if "end user license agreement" in lowered or "accept_eula" in lowered:
            return WorkIqError(
                "eula_required",
                safe,
                "Review https://github.com/microsoft/work-iq, then explicitly "
                "run 'workiq-smart-tool accept-eula --yes'.",
                details={
                    "requires_confirmation": True,
                    "confirmation_type": "legal_terms",
                    "terms_url": "https://github.com/microsoft/work-iq",
                    "action": {
                        "capability": "accept-eula",
                        "arguments": ["--yes"],
                    },
                },
            )
        if "policy" in lowered or "forbidden" in lowered:
            return WorkIqError(
                "policy_denied",
                safe,
                "Ask the Microsoft 365 administrator to review Work IQ MCP "
                "policy. Do not retry automatically.",
            )
        if (
            "authentication" in lowered
            or "sign in" in lowered
            or "login" in lowered
            or "unauthorized" in lowered
        ):
            return WorkIqError(
                "authentication_required",
                safe,
                "Run 'workiq-smart-tool authenticate' and complete Microsoft "
                "365 sign-in.",
            )
        if "429" in lowered or "throttl" in lowered:
            return WorkIqError(
                "rate_limited",
                safe,
                "Wait for the service retry interval, then retry.",
                retryable=True,
            )
        return WorkIqError(
            "workiq_request_failed",
            safe,
            "Review the resource path, account permissions, and Work IQ tenant "
            "policy, then retry.",
        )
