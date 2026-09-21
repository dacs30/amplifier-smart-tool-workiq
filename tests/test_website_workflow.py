from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "website.yml"


class WebsiteWorkflowTests(unittest.TestCase):
    def test_deploy_job_is_skipped_when_github_pages_is_not_enabled(self):
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        # PyYAML follows YAML 1.1 and parses the unquoted GitHub Actions
        # `on:` trigger key as True, so this test intentionally inspects jobs.
        jobs = workflow["jobs"]
        pages_job = jobs["pages"]
        deploy_job = jobs["deploy"]

        self.assertEqual(pages_job["permissions"], {"pages": "read"})
        self.assertEqual(
            pages_job["outputs"],
            {"enabled": "${{ steps.status.outputs.enabled }}"},
        )
        status_step = next(
            step for step in pages_job["steps"] if step.get("id") == "status"
        )
        self.assertEqual(status_step["env"], {"GH_TOKEN": "${{ github.token }}"})
        status_script = status_step["run"]
        self.assertIn("404", status_script)
        self.assertRegex(status_script, r"enabled=true.+GITHUB_OUTPUT")
        self.assertRegex(status_script, r"enabled=false.+GITHUB_OUTPUT")

        self.assertEqual(deploy_job["needs"], ["build", "pages"])
        self.assertIn("needs.pages.outputs.enabled == 'true'", deploy_job["if"])
        self.assertIn("github.event_name == 'push'", deploy_job["if"])
        self.assertIn("workflow_dispatch", deploy_job["if"])
        self.assertEqual(deploy_job["environment"]["name"], "github-pages")
        self.assertEqual(
            deploy_job["environment"]["url"],
            "${{ steps.deployment.outputs.page_url }}",
        )


if __name__ == "__main__":
    unittest.main()
