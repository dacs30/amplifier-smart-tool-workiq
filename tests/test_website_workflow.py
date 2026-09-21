from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "website.yml"


def job_block(workflow: str, job_name: str) -> str:
    match = re.search(rf"^  {re.escape(job_name)}:\n", workflow, re.MULTILINE)
    if match is None:
        raise AssertionError(f"job {job_name!r} not found")

    next_job = re.search(r"^  [A-Za-z0-9_-]+:\n", workflow[match.end() :], re.MULTILINE)
    if next_job is None:
        return workflow[match.start() :]
    return workflow[match.start() : match.end() + next_job.start()]


class WebsiteWorkflowTests(unittest.TestCase):
    def test_deploy_job_is_skipped_when_github_pages_is_not_enabled(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        pages_job = job_block(workflow, "pages")
        deploy_job = job_block(workflow, "deploy")

        self.assertIn("permissions:\n      pages: write", pages_job)
        self.assertIn("outputs:\n      enabled: ${{ steps.status.outputs.enabled }}", pages_job)
        self.assertIn("id: status", pages_job)
        self.assertIn("set -euo pipefail", pages_job)
        self.assertIn("Authorization: Bearer $GH_TOKEN", pages_job)
        self.assertIn("$GITHUB_API_URL/repos/$GITHUB_REPOSITORY/pages", pages_job)
        self.assertIn('elif [ "$status" = "404" ]; then', pages_job)
        self.assertIn("skipping deployment", pages_job)

        self.assertIn("if: needs.pages.outputs.enabled == 'true'", deploy_job)
        self.assertIn("needs: [build, pages]", deploy_job)
        self.assertIn("environment:\n      name: github-pages", deploy_job)


if __name__ == "__main__":
    unittest.main()
