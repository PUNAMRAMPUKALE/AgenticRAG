from __future__ import annotations

import unittest

from app.infrastructure.agents.operations_agent import call_tools as ops_tools
from app.infrastructure.agents.policy_agent import call_tools as policy_tools
from app.infrastructure.agents.specialists import specialist_for
from app.infrastructure.agents.supervisor import keyword_intent
from app.infrastructure.agents.treasury_agent import call_tools as treasury_tools


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

    def test_routes_to_separate_specialists(self):
        self.assertEqual(specialist_for("policy").NAME, "policy")
        self.assertEqual(specialist_for("operations").NAME, "operations")
        self.assertEqual(specialist_for("treasury").NAME, "treasury")
        self.assertEqual(specialist_for("unknown").NAME, "policy")

    def test_specialist_tools_are_distinct_mocks(self):
        policy = policy_tools("KYC")
        ops = ops_tools("SOP")
        treasury = treasury_tools("liquidity")
        self.assertEqual(policy[0]["tool"], "lookup_kyc_onboarding")
        self.assertTrue(policy[0]["mock"])
        self.assertEqual(ops[0]["tool"], "lookup_payment_sop")
        self.assertEqual(treasury[0]["tool"], "lookup_liquidity_snapshot")
        self.assertNotEqual(policy[0]["tool"], ops[0]["tool"])
        self.assertNotEqual(ops[0]["tool"], treasury[0]["tool"])


if __name__ == "__main__":
    unittest.main()
