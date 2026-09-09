from __future__ import annotations

import unittest

from app.evals.score import score_case, summarize


class ScoreTests(unittest.TestCase):
    def test_retrieval_and_phrase_pass(self):
        scored = score_case(
            {
                "id": "kyc",
                "query": "KYC?",
                "expected_file_ids": ["KYC_Client_Onboarding"],
                "must_contain": ["kyc"],
            },
            citations=[{"file_id": "compliance/KYC_Client_Onboarding_Procedure"}],
            answer="The KYC procedure requires identity checks.",
        )
        self.assertTrue(scored.passed)
        self.assertTrue(scored.retrieval_hit)

    def test_wrong_file_fails(self):
        scored = score_case(
            {
                "id": "kyc",
                "query": "KYC?",
                "expected_file_ids": ["KYC_Client_Onboarding"],
                "must_contain": ["kyc"],
            },
            citations=[{"file_id": "treasury/Liquidity_Risk_Report_Q2_2026"}],
            answer="The KYC procedure requires identity checks.",
        )
        self.assertFalse(scored.passed)
        self.assertFalse(scored.retrieval_hit)

    def test_abstain_when_empty(self):
        scored = score_case(
            {"id": "out", "query": "Bitcoin price?", "abstain": True},
            citations=[],
            answer="I could not find this in the knowledge base.",
        )
        self.assertTrue(scored.passed)

    def test_suite_threshold(self):
        a = score_case(
            {"id": "a", "expected_file_ids": ["SOP"], "must_contain": ["payment"]},
            citations=[{"file_id": "operations/Payment_Operations_SOP"}],
            answer="payment ops",
        )
        b = score_case(
            {"id": "b", "expected_file_ids": ["SOP"], "must_contain": ["payment"]},
            citations=[],
            answer="no",
        )
        report = summarize([a, b], 0.5)
        self.assertTrue(report["ok"])
        self.assertEqual(report["passed"], 1)

    def test_routing_mismatch_fails(self):
        scored = score_case(
            {
                "id": "kyc",
                "expected_file_ids": ["KYC_Client_Onboarding"],
                "must_contain": ["kyc"],
                "expected_intent": "policy",
            },
            citations=[{"file_id": "compliance/KYC_Client_Onboarding_Procedure"}],
            answer="The KYC procedure requires identity checks.",
            predicted_intent="treasury",
        )
        self.assertFalse(scored.passed)
        self.assertFalse(scored.routing_ok)
        self.assertGreater(scored.mrr, 0)


if __name__ == "__main__":
    unittest.main()
