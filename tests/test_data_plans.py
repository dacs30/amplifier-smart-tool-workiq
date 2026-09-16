from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from amplifier_smart_tool_workiq.data_plans import DataPlan
from amplifier_smart_tool_workiq.errors import WorkIqError


def plan_value() -> dict:
    return {
        "format": 1,
        "name": "daily-context",
        "description": "Fetch bounded context.",
        "requests": [
            {
                "name": "messages",
                "path": "/me/messages?$select=id,subject&$top=10",
            }
        ],
    }


class DataPlanTests(unittest.TestCase):
    def test_validates_bounded_read_only_plan(self):
        plan = DataPlan.from_dict(plan_value())

        self.assertEqual(plan.name, "daily-context")
        self.assertEqual(
            plan.paths(),
            ["/me/messages?$select=id,subject&$top=10"],
        )

    def test_rejects_unbounded_or_unsafe_requests(self):
        for path in (
            "/me/messages?$top=10",
            "/me/messages?$select=id&$top=101",
            "https://graph.microsoft.com/v1.0/me/messages?$select=id",
        ):
            value = plan_value()
            value["requests"][0]["path"] = path
            with self.subTest(path=path):
                with self.assertRaises(WorkIqError):
                    DataPlan.from_dict(value)

    def test_rejects_duplicate_request_names(self):
        value = plan_value()
        value["requests"].append(dict(value["requests"][0]))

        with self.assertRaises(WorkIqError) as context:
            DataPlan.from_dict(value)

        self.assertEqual(context.exception.code, "duplicate_data_plan_request")

    def test_reads_plan_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "plan.json"
            path.write_text(json.dumps(plan_value()), encoding="utf-8")

            self.assertEqual(DataPlan.read(path).name, "daily-context")


if __name__ == "__main__":
    unittest.main()
