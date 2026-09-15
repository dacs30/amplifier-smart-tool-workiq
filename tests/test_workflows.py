from __future__ import annotations

import unittest
from datetime import date

from amplifier_smart_tool_workiq.errors import WorkIqError
from amplifier_smart_tool_workiq.workflows import WorkIqService, validate_fetch_path


class RecordingClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return {"ok": True}


class WorkflowTests(unittest.TestCase):
    def test_fetch_requires_allowed_relative_path_and_select(self):
        valid = "/me/messages?$select=id,subject&$top=10"
        self.assertEqual(validate_fetch_path(valid), valid)

        for invalid in (
            "https://graph.microsoft.com/v1.0/me/messages?$select=id",
            "/groups?$select=id",
            "/me/messages?$top=10",
            "/me/messages?$select=id&$top=101",
            "/users/x/authentication/methods?$select=id",
            "/users/x/%61uthentication/methods?$select=id",
            "/users/x%2fauthentication/methods?$select=id",
            "/me/../users/x/messages?$select=id",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(WorkIqError):
                    validate_fetch_path(invalid)

    def test_daily_briefing_is_read_only_and_date_bound(self):
        client = RecordingClient()
        service = WorkIqService(client)

        service.daily_briefing(
            briefing_date=date(2026, 9, 15),
            time_zone="America/New_York",
        )

        name, arguments = client.calls[0]
        self.assertEqual(name, "ask")
        self.assertEqual(arguments["timeZone"], "America/New_York")
        self.assertIn("2026-09-15", arguments["question"])
        self.assertIn("Do not send messages", arguments["question"])

    def test_meeting_prep_includes_target(self):
        client = RecordingClient()
        service = WorkIqService(client)

        service.meeting_prep(
            meeting="Architecture review",
            meeting_date=date(2026, 9, 16),
        )

        _, arguments = client.calls[0]
        self.assertIn("Architecture review", arguments["question"])
        self.assertIn("2026-09-16", arguments["question"])


if __name__ == "__main__":
    unittest.main()
