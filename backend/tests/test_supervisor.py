from __future__ import annotations

import unittest

from app.infrastructure.agents.supervisor import keyword_intent


class SupervisorTests(unittest.TestCase):
    def test_policy(self):
        self.assertEqual(keyword_intent("What is the KYC client onboarding procedure?"), "policy")

    def test_operations(self):
        self.assertEqual(
            keyword_intent("What does the payment operations standard operating procedure cover?"),
            "operations",
        )

    def test_treasury(self):
        self.assertEqual(keyword_intent("Summarize the Q2 2026 liquidity risk report."), "treasury")

    def test_escalation(self):
        self.assertEqual(keyword_intent("I am furious and want to file a complaint"), "escalation")

    def test_unrecognised_defaults_to_policy(self):
        self.assertEqual(keyword_intent("hello"), "policy")


if __name__ == "__main__":
    unittest.main()
