"""Tests for note.py: python -m unittest discover -s .github/live -p "test_*.py" """

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from note import CONFIRMED_NOTE, command_text, fresh_record, note, scenario_ids

TO = "model-b"
IDS = ["address_change", "other_customer_data", "policy_question", "refund_outside_window"]


def result(scenario: str, verdict: str, confirmed: bool = False) -> dict:
    words = f"A changed tool call; {CONFIRMED_NOTE}." if confirmed else "A changed tool call."
    return {"scenario_id": scenario, "verdict": verdict, "explanation": words}


def record(results: list[dict], exit_code: int = 1, to: str = TO) -> dict:
    return {"from_model": "model-a", "to_model": to, "exit_code": exit_code, "results": results}


class NoteTest(unittest.TestCase):
    def test_names_the_regressions_and_why_github_shows_a_failure(self) -> None:
        rec = record(
            [
                result("other_customer_data", "regression", True),
                result("refund_outside_window", "regression", True),
                result("address_change", "unchanged"),
                result("policy_question", "changed_minor"),
            ]
        )
        level, title, summary = note(rec, set(IDS), TO, 1)
        self.assertEqual((level, title), ("error", "Modelpin found 2 regressions"))
        head = summary.splitlines()[2]
        self.assertTrue(
            head.startswith(
                "2 of 4 scenarios regressed moving to model-b, each confirmed on a second set of runs: "
                "other_customer_data, refund_outside_window."
            )
        )
        self.assertIn("so GitHub shows this run as failed", head)
        self.assertIn("| `policy_question` | Minor change |", summary)
        self.assertIn("| `other_customer_data` | Regression, confirmed on a second set of runs |", summary)
        self.assertNotIn("changed tool call", summary)

    def test_says_what_was_not_measured(self) -> None:
        rec = record([result("other_customer_data", "regression"), result("address_change", "unchanged")])
        _, _, summary = note(rec, set(IDS), TO, 1)
        head = summary.splitlines()[2]
        self.assertTrue(head.startswith("1 of 2 scenarios regressed moving to model-b: other_customer_data."))
        self.assertIn("Modelpin couldn't measure 2 other scenarios.", head)
        self.assertIn("| `policy_question` | Not compared |", summary)

    def test_a_clean_check_and_one_with_gaps(self) -> None:
        clean = record([result(s, "unchanged") for s in IDS], exit_code=0)
        self.assertEqual(note(clean, set(IDS), TO, 0)[:2], ("notice", "Modelpin found no regression"))
        gaps = record([result(s, "unchanged") for s in IDS[:3]], exit_code=0)
        level, _, summary = note(gaps, set(IDS), TO, 0)
        self.assertEqual(level, "warning")
        self.assertIn("couldn't measure 1 of 4 scenarios", summary)

    def test_never_calls_anything_a_regression_without_a_record(self) -> None:
        for code in (1, 2, 4):
            level, title, summary = note(None, set(IDS), TO, code)
            self.assertEqual((level, title), ("warning", "Modelpin didn't finish the check"))
            self.assertNotIn("regress", summary)
        self.assertIn("couldn't compare any scenario", note(None, set(IDS), TO, 3)[2])

    def test_reads_only_a_fresh_record_for_this_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / ".modelpin"
            (store / "runs").mkdir(parents=True)
            old = store / "runs" / "check-a.json"
            old.write_text(json.dumps(record([result("address_change", "regression")])), encoding="utf-8")
            os.utime(old, (time.time() - 3600, time.time() - 3600))
            other = store / "runs" / "check-b.json"
            other.write_text(json.dumps(record([], to="model-c")), encoding="utf-8")
            since = time.time() - 60
            self.assertIsNone(fresh_record(store, since, TO, 1))
            mine = store / "runs" / "check-c.json"
            mine.write_text(json.dumps(record([result("address_change", "unchanged")])), encoding="utf-8")
            self.assertIsNone(fresh_record(store, since, TO, 0))
            found = fresh_record(store, since, TO, 1)
            assert found is not None
            self.assertEqual(found["results"][0]["verdict"], "unchanged")

    def test_scenarios_as_modelpin_loads_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "results").mkdir()
            (root / ".hidden").mkdir()
            (root / "a.json").write_text('{"id": "a"}', encoding="utf-8")
            (root / "manifest.json").write_text('{"id": "m"}', encoding="utf-8")
            (root / "results" / "r.json").write_text('{"id": "r"}', encoding="utf-8")
            (root / ".hidden" / "h.json").write_text('{"id": "h"}', encoding="utf-8")
            self.assertEqual(scenario_ids(root), {"a"})

    def test_workflow_command_escaping(self) -> None:
        self.assertEqual(command_text("a: b, 100%\nc", prop=True), "a%3A b%2C 100%25%0Ac")
        self.assertEqual(command_text("a: b, c"), "a: b, c")


if __name__ == "__main__":
    unittest.main()
