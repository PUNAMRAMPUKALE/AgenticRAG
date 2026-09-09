from __future__ import annotations

import unittest

from app.infrastructure.agents.guards import SAFE_FALLBACK, input_guard, output_guard


class GuardTests(unittest.TestCase):
    def test_input_blocks_ssn_without_leaking_reason(self):
        blocked, reason = input_guard("What is my SSN on file?")
        self.assertEqual(blocked, SAFE_FALLBACK)
        self.assertEqual(reason, "ssn")
        self.assertNotIn("ssn", blocked.lower())

    def test_input_allows_policy_question(self):
        blocked, reason = input_guard("What is the KYC client onboarding procedure?")
        self.assertIsNone(blocked)
        self.assertIsNone(reason)

    def test_output_strips_ssn(self):
        text = output_guard("Client SSN is 123-45-6789.", "kyc")
        self.assertEqual(text, SAFE_FALLBACK)

    def test_output_allows_clean_answer(self):
        text = output_guard("KYC requires identity checks.", "kyc")
        self.assertIn("KYC", text)


if __name__ == "__main__":
    unittest.main()
