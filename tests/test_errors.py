import unittest

from amplifier_smart_tool_workiq.errors import sanitize


class SanitizationTests(unittest.TestCase):
    def test_redacts_bearer_and_token_fields(self):
        value = sanitize(
            'Authorization: Bearer abc.def token; access_token="secret-value"'
        )
        self.assertNotIn("abc.def", value)
        self.assertNotIn("secret-value", value)
        self.assertIn("[REDACTED]", value)


if __name__ == "__main__":
    unittest.main()
