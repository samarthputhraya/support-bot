"""Tests for send_scan.py: python -m unittest discover -s .github/live -p "test_*.py" (needs modelpin-relay)."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import send_scan
from modelpin_relay.transport import SendResult

REPO = "acme-labs/help-desk"


def scan_event(**changes: object) -> dict:
    """What `modelpin-relay publish-watch --ci local` builds in a clone of github.com/acme-labs/help-desk."""
    event = {
        "schema": "modelpin.atlassian/v1",
        "event_id": "33333333-3333-4333-8333-333333333333",
        "kind": "watch",
        "sent_at": "2026-11-14T12:00:00Z",
        "relay_version": "0.1.1",
        "modelpin_version": "0.5.3",
        "sample": False,
        "source": {
            "ci": "local",
            "repo_key": f"github:{REPO}",
            "repo_url": None,
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "branch": "main",
            "pr_id": None,
            "pr_url": None,
            "build_url": None,
            "build_number": None,
            "jira_keys": ["KAN-1"],
            "code_refs": [],
            "history_keys": ["KAN-2"],
        },
        "check": None,
        "watch": {
            "registry_newest_fetched_at": "2026-11-05",
            "exit_code": 1,
            "models": [
                {"id": "claude-sonnet-4-5-20250929", "code_refs": ["src/app.py"], "history_keys": ["KAN-3"]},
            ],
        },
        "truncated": ["history_keys"],
    }
    event.update(changes)
    return event


class CheckedTest(unittest.TestCase):
    def test_keeps_the_scan_and_its_file_paths_and_drops_every_work_item_key(self) -> None:
        out = send_scan.checked(scan_event(), REPO)
        self.assertEqual(out["source"]["repo_key"], f"github:{REPO}")
        self.assertEqual(out["source"]["jira_keys"], [])
        self.assertEqual(out["source"]["history_keys"], [])
        self.assertEqual(out["watch"]["models"][0]["history_keys"], [])
        self.assertEqual(out["watch"]["models"][0]["code_refs"], ["src/app.py"])
        self.assertEqual(out["truncated"], [])
        self.assertIsNone(out["check"])
        self.assertIs(out["sample"], False)

    def test_refuses_anything_but_one_scan_of_the_tickets_repository(self) -> None:
        bad = [
            scan_event(kind="check"),
            scan_event(schema="something/v2"),
            scan_event(sample=True),
            scan_event(check={"run_key": "x"}),
            scan_event(source={**scan_event()["source"], "repo_key": "github:acme-labs/other"}),
            scan_event(source={**scan_event()["source"], "repo_key": "github:samarthputhraya/support-bot"}),
            scan_event(source={**scan_event()["source"], "ci": "github"}),
            scan_event(watch={"models": [{"id": "m"}] * 201}),
            scan_event(watch={"models": "all"}),
            scan_event(watch={"models": ["m"]}),
            "not an event",
        ]
        for event in bad:
            with self.subTest(event=str(event)[:60]), self.assertRaises(send_scan.Refused):
                send_scan.checked(event, REPO)

    def test_the_repository_must_match_exactly(self) -> None:
        with self.assertRaises(send_scan.Refused):
            send_scan.checked(scan_event(), "Acme-Labs/help-desk")


class MainTest(unittest.TestCase):
    def run_main(self, event: object, env: dict[str, str], result: SendResult | None = None) -> tuple[int, str, list]:
        sent: list = []

        def fake_send(url: str, key: str, body: bytes) -> SendResult:
            sent.append((url, key, json.loads(body)))
            return result or SendResult(ok=True, status=200, app_status="accepted", attempts=1, error=None)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "event.json"
            path.write_text(json.dumps(event), encoding="utf-8")
            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
                send_scan, "send_event", fake_send
            ), redirect_stdout(out):
                code = send_scan.main(["--event", str(path), "--repo", REPO])
        return code, out.getvalue(), sent

    ENV = {"MODELPIN_WEBHOOK_URL": "https://a.webtrigger.atlassian.app/public/x", "MODELPIN_WEBHOOK_SECRET": "k" * 64}

    def test_sends_the_checked_scan_and_prints_only_the_outcome(self) -> None:
        code, printed, sent = self.run_main(scan_event(), self.ENV)
        self.assertEqual(code, 0)
        self.assertEqual(printed.strip(), "Scan sent to Jira: 1 model, HTTP 200 accepted.")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][2]["source"]["jira_keys"], [])
        self.assertNotIn("webtrigger", printed)
        self.assertNotIn("k" * 64, printed)

    def test_sends_nothing_for_another_repository_or_without_the_tickets_address(self) -> None:
        other = scan_event(source={**scan_event()["source"], "repo_key": "github:acme-labs/other"})
        code, printed, sent = self.run_main(other, self.ENV)
        self.assertEqual((code, sent), (1, []))
        self.assertIn("::error::Not sent: the scan job's event is for another repository.", printed)
        code, printed, sent = self.run_main(scan_event(), {"MODELPIN_WEBHOOK_URL": "", "MODELPIN_WEBHOOK_SECRET": ""})
        self.assertEqual((code, sent), (1, []))

    def test_fails_the_step_when_jira_refuses(self) -> None:
        refused = SendResult(ok=False, status=401, app_status="unauthorized", attempts=1, error=None)
        code, printed, _ = self.run_main(scan_event(), self.ENV, refused)
        self.assertEqual(code, 1)
        self.assertIn("Jira didn't accept the scan: HTTP 401 unauthorized.", printed)


if __name__ == "__main__":
    unittest.main()
