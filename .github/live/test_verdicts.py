"""Tests for verdicts.py: python -m unittest discover -s .github/live -p "test_*.py" """

import unittest

from note import CONFIRMED_NOTE
from verdicts import line


class VerdictsTest(unittest.TestCase):
    def test_one_line_with_verdicts_confirmations_and_tokens_only(self) -> None:
        record = {
            "results": [
                {"scenario_id": "refund_flow", "verdict": "unchanged", "explanation": "A reply."},
                {"scenario_id": "other_customer_data", "verdict": "regression", "explanation": f"x; {CONFIRMED_NOTE}."},
                {"scenario_id": "policy_question", "verdict": "regression", "explanation": "Not confirmed."},
            ],
            "candidate_runs": {
                "refund_flow": [{"tokens_in": 100, "tokens_out": 7, "final_output": "A secret reply"}],
                "policy_question": [{"tokens_in": 50, "tokens_out": True}, "odd"],
            },
        }
        self.assertEqual(
            line(record, 1),
            "Verdicts: exit=1 other_customer_data=regression:confirmed policy_question=regression "
            "refund_flow=unchanged tokens_in=150 tokens_out=7",
        )
        self.assertNotIn("secret", line(record, 1))

    def test_no_record_and_odd_results(self) -> None:
        self.assertEqual(line(None, 4), "Verdicts: exit=4 record=none")
        odd = {"results": [{"scenario_id": "a b", "verdict": "unchanged"}, {"scenario_id": "c", "verdict": "x"}]}
        self.assertEqual(line(odd, 0), "Verdicts: exit=0 unreadable=result unreadable=result tokens_in=0 tokens_out=0")


if __name__ == "__main__":
    unittest.main()
