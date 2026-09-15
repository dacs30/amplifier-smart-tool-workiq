import unittest

from amplifier_smart_tool_workiq.errors import WorkIqError, sanitize


class SanitizationTests(unittest.TestCase):
    def test_redacts_bearer_and_token_fields(self):
        value = sanitize(
            'Authorization: Bearer abc.def token; access_token="secret-value"'
        )
        self.assertNotIn("abc.def", value)
        self.assertNotIn("secret-value", value)
        self.assertIn("[REDACTED]", value)

    def test_error_includes_optional_structured_details(self):
        error = WorkIqError(
            "confirmation_required",
            "Confirmation is required.",
            "Ask the user.",
            details={"requires_confirmation": True},
        )

        self.assertEqual(
            error.as_dict()["details"],
            {"requires_confirmation": True},
        )


if __name__ == "__main__":
    unittest.main()
