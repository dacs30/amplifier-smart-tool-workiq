from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from amplifier_smart_tool_workiq.errors import WorkIqError
from amplifier_smart_tool_workiq.profiles import (
    WorkflowProfile,
    WorkflowStore,
    parse_input_values,
)


def profile_value() -> dict:
    return {
        "format": 1,
        "name": "project-status",
        "description": "Prepare a project review.",
        "inputs": ["project", "review_date"],
        "prompt": "Review {project} as of {review_date}.",
    }


class WorkflowProfileTests(unittest.TestCase):
    def test_validates_and_renders_exact_inputs(self):
        profile = WorkflowProfile.from_dict(profile_value())

        rendered = profile.render(
            {"project": "Alpha", "review_date": "2026-09-15"}
        )

        self.assertEqual(rendered, "Review Alpha as of 2026-09-15.")

    def test_rejects_unknown_fields_and_placeholder_mismatch(self):
        value = profile_value()
        value["extra"] = True
        with self.assertRaises(WorkIqError):
            WorkflowProfile.from_dict(value)

        value = profile_value()
        value["name"] = "a" * 65
        with self.assertRaises(WorkIqError):
            WorkflowProfile.from_dict(value)

        value = profile_value()
        value["inputs"] = ["project"]
        with self.assertRaises(WorkIqError):
            WorkflowProfile.from_dict(value)

    def test_store_create_list_get_and_delete(self):
        profile = WorkflowProfile.from_dict(profile_value())
        with tempfile.TemporaryDirectory() as temporary:
            store = WorkflowStore(Path(temporary))
            destination = store.create(profile)

            self.assertTrue(destination.is_file())
            self.assertEqual([item.name for item in store.list()], ["project-status"])
            self.assertEqual(store.get("project-status"), profile)

            store.delete("project-status")
            self.assertEqual(store.list(), [])

    def test_store_does_not_replace_implicitly(self):
        profile = WorkflowProfile.from_dict(profile_value())
        with tempfile.TemporaryDirectory() as temporary:
            store = WorkflowStore(Path(temporary))
            store.create(profile)
            with self.assertRaises(WorkIqError):
                store.create(profile)

    def test_concurrent_creates_do_not_overwrite(self):
        profile = WorkflowProfile.from_dict(profile_value())
        with tempfile.TemporaryDirectory() as temporary:
            store = WorkflowStore(Path(temporary))

            def create() -> str:
                try:
                    store.create(profile)
                    return "created"
                except WorkIqError as error:
                    return error.code

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: create(), range(2)))

            self.assertCountEqual(results, ["created", "workflow_exists"])
            self.assertEqual(store.get("project-status"), profile)

    def test_store_rejects_filename_and_profile_name_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = profile_value()
            value["name"] = "other-workflow"
            (root / "project-status.json").write_text(
                json.dumps(value),
                encoding="utf-8",
            )
            store = WorkflowStore(root)

            with self.assertRaises(WorkIqError) as context:
                store.get("project-status")

            self.assertEqual(context.exception.code, "invalid_stored_workflow")
            self.assertTrue((root / "project-status.json").exists())

    def test_store_wraps_configuration_directory_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "workflows"
            root.write_text("not a directory", encoding="utf-8")
            store = WorkflowStore(root)

            with self.assertRaises(WorkIqError) as context:
                store.create(WorkflowProfile.from_dict(profile_value()))

            self.assertEqual(context.exception.code, "workflow_write_failed")

    def test_reads_profile_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text(json.dumps(profile_value()), encoding="utf-8")
            self.assertEqual(WorkflowProfile.read(path).name, "project-status")

    def test_parses_cli_inputs_without_duplicates(self):
        self.assertEqual(
            parse_input_values(["project=Alpha", "review_date=2026-09-15"]),
            {"project": "Alpha", "review_date": "2026-09-15"},
        )
        with self.assertRaises(WorkIqError):
            parse_input_values(["project=Alpha", "project=Beta"])


if __name__ == "__main__":
    unittest.main()
