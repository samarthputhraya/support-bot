"""Tests for record.py: python -m unittest discover -s .github/live -p "test_*.py" """

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from record import FIRST_DAY, LAST_DAY, MODEL, append, outcome, should_record


class Refused(Exception):
    def __init__(self, status: int, body: object) -> None:
        super().__init__("refused")
        self.status_code = status
        self.body = body


class RecordTest(unittest.TestCase):
    def test_records_only_inside_the_window_on_a_schedule_and_always_by_hand(self) -> None:
        self.assertEqual(FIRST_DAY, date(2026, 11, 28))
        self.assertEqual(LAST_DAY, date(2026, 12, 3))
        self.assertTrue(should_record("schedule", date(2026, 11, 28)))
        self.assertTrue(should_record("schedule", date(2026, 12, 3)))
        self.assertFalse(should_record("schedule", date(2026, 11, 27)))
        self.assertFalse(should_record("schedule", date(2026, 12, 4)))
        self.assertTrue(should_record("workflow_dispatch", date(2026, 11, 20)))

    def test_an_answer_and_a_refusal_are_recorded_as_status_and_type_never_a_reply(self) -> None:
        self.assertEqual(outcome(lambda: None), {"answered": True, "status": 200, "error_type": None})
        body = {"type": "error", "error": {"type": "not_found_error", "message": "model: claude-sonnet-4-5-20250929"}}

        def refuse() -> None:
            raise Refused(404, body)

        self.assertEqual(outcome(refuse), {"answered": False, "status": 404, "error_type": "not_found_error"})

        def broken() -> None:
            raise ConnectionError("no network")

        # No HTTP answer at all: said as such, with the exception's class, never its message.
        self.assertEqual(outcome(broken), {"answered": False, "status": None, "error_type": "ConnectionError"})

    def test_appends_one_line_per_run_with_the_run_that_made_it(self) -> None:
        path = Path(tempfile.mkdtemp()) / "retirement-record.jsonl"
        env = {
            "GITHUB_RUN_ID": "1234",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "samarthputhraya/support-bot",
        }
        append(path, "2026-12-01T06:00:12Z", {"answered": False, "status": 404, "error_type": "not_found_error"}, env)
        append(path, "2026-12-02T06:00:09Z", {"answered": False, "status": 404, "error_type": "not_found_error"}, env)
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            lines[0],
            {
                "at": "2026-12-01T06:00:12Z",
                "model": MODEL,
                "answered": False,
                "status": 404,
                "error_type": "not_found_error",
                "run_id": "1234",
                "run_url": "https://github.com/samarthputhraya/support-bot/actions/runs/1234",
            },
        )

    def test_a_run_outside_github_names_no_run(self) -> None:
        path = Path(tempfile.mkdtemp()) / "retirement-record.jsonl"
        append(path, "2026-11-20T06:00:00Z", {"answered": True, "status": 200, "error_type": None}, {})
        line = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsNone(line["run_id"])
        self.assertIsNone(line["run_url"])


if __name__ == "__main__":
    unittest.main()
