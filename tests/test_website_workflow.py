from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "website.yml"


class WebsiteWorkflowTests(unittest.TestCase):
    def test_deploy_skips_when_github_pages_is_not_enabled(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("Check GitHub Pages status", workflow)
        self.assertIn("Authorization: Bearer $GH_TOKEN", workflow)
        self.assertIn("$GITHUB_API_URL/repos/$GITHUB_REPOSITORY/pages", workflow)
        self.assertIn('elif [ "$status" = "404" ]; then', workflow)
        self.assertIn("skipping deployment", workflow)
        self.assertIn("if: steps.pages.outputs.enabled == 'true'", workflow)


if __name__ == "__main__":
    unittest.main()
