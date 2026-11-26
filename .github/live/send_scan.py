"""Sends a repository scan to the one Jira site its ticket names, signed for that one request.

The workflow's scan job read the named repository's files, which this job never sees; it hands over one event.json
built by `modelpin-relay publish-watch --ci local`. That job held no secret, and its input was a stranger's
repository, so this job trusts it for two things only: which model IDs Modelpin found, and in which files. It checks
that the event is one scan (a watch event) of exactly the repository the ticket names. Then it asks its own pinned
Modelpin for every fact about those IDs (status, dates, replacement, the vendor page, the check command), so a scan
job that misbehaved could never put a false date or a link of its own on a judge's work item (security review of
the scan, 14 Nov 2026, F3). It sends no work item keys: a repository's branch names and commit messages come from
its own committers, and must never point at a work item on the judge's site.

It prints only the outcome, never the event, the address or the key.

    python .github/live/send_scan.py --event <event.json> --repo <owner/name>
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from modelpin_relay.payload import MAX_WATCH_MODELS, SCHEMA_ID, build_watch
from modelpin_relay.transport import send_event
from modelpin_relay.truncate import EventTooLarge, fit

MAX_FILE_BYTES = 2_000_000
SOURCE_FIELDS = ("ci", "repo_key", "repo_url", "commit", "branch", "pr_id", "pr_url", "build_url", "build_number")
EVENT_FIELDS = ("schema", "event_id", "kind", "sent_at", "relay_version", "modelpin_version")
# A model ID as Modelpin's scan reports one: no spaces, quotes or control characters.
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}")
# A file path relative to the repository, kept only when plain: a stranger's file name could otherwise hold a sentence
# or bidirectional controls that read as Modelpin's own words on a judge's work item (security review S1, 15 Nov 2026).
CODE_REF = re.compile(r"[A-Za-z0-9._@+-]+(?:/[A-Za-z0-9._@+-]+)*")
MAX_CODE_REF = 200
# The event schema's limit on one model's files (codeRefs.maxItems), so a merged row can't make Jira refuse the scan.
MAX_REFS = 20
# A branch name, kept only when plain, for the same reason as a file path; otherwise none is sent.
BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,100}")
PROVIDERS = ["anthropic", "openai", "google"]
# Modelpin 0.5.7's registry data, read with this job's 0.5.3 through its --registry option, so the facts match the
# Jira app's copy (scripts/registry_from_wheel.py in the app's repository; 0.5.5's on 23 Nov 2026, 0.5.7's on 26 Nov 2026).
REGISTRY = Path(__file__).resolve().parent / "models.json"


class Refused(Exception):
    """The event isn't a scan of the ticket's repository; nothing is sent."""


def found(event: Any, repo: str) -> list[tuple[str, list[str]]]:
    """The model IDs the scan job found and the files it found each in, once checked; or Refused with the reason."""
    if not isinstance(event, dict):
        raise Refused("the scan job's file isn't an event")
    if event.get("schema") != SCHEMA_ID or event.get("kind") != "watch":
        raise Refused("the scan job's event isn't a scan")
    if event.get("check") is not None or event.get("sample") is not False:
        raise Refused("the scan job's event isn't a scan")
    source = event.get("source")
    watch = event.get("watch")
    if not isinstance(source, dict) or not isinstance(watch, dict):
        raise Refused("the scan job's event isn't a scan")
    if source.get("repo_key") != f"github:{repo}" or source.get("ci") != "local":
        raise Refused("the scan job's event is for another repository")
    models = watch.get("models")
    if not isinstance(models, list) or len(models) > MAX_WATCH_MODELS:
        raise Refused("the scan job's event lists no models, or too many")
    out: dict[str, list[str]] = {}
    for model in models:
        model_id = model.get("id") if isinstance(model, dict) else None
        # Left out, not refused: one odd entry (a class name with a space, say) shouldn't empty the whole scan; it
        # never reaches Modelpin's config or Jira (security review S2, 15 Nov 2026).
        if not isinstance(model_id, str) or not MODEL_ID.fullmatch(model_id):
            continue
        refs = model.get("code_refs")
        refs = refs if isinstance(refs, list) else []
        clean = [r for r in refs if isinstance(r, str) and len(r) <= MAX_CODE_REF and CODE_REF.fullmatch(r)]
        kept = out.setdefault(model_id, [])
        for ref in clean:
            if ref not in kept and len(kept) < MAX_REFS:
                kept.append(ref)
    return list(out.items())


def registry_facts(ids: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """This job's own Modelpin on these IDs: each one's row (the relay's kept fields), and the run's watch payload."""
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "facts.yaml"
        # JSON is YAML, and json.dumps quotes every ID, so an ID can't change the config's meaning.
        config.write_text(json.dumps({"models": ids, "providers": PROVIDERS}), encoding="utf-8")
        run = subprocess.run(
            [
                "modelpin", "watch", "--json", "--config", str(config), "--store-dir", str(Path(tmp) / "store"),
                "--registry", str(REGISTRY),
            ],
            capture_output=True,
            text=True,
            cwd=tmp,
            timeout=120,
            check=False,
            # It reads IDs that came from a stranger's repository, so it gets no Jira address or key (security
            # review S3, 15 Nov 2026).
            env={k: v for k, v in os.environ.items() if not k.startswith("MODELPIN_WEBHOOK_")},
        )
    try:
        doc = json.loads(run.stdout)
    except ValueError as exc:
        raise Refused("this job's Modelpin couldn't look up the model IDs") from exc
    built = build_watch(doc if isinstance(doc, dict) else {}).payload
    return {m["id"]: m for m in built["models"]}, built


def unknown_row(model_id: str) -> dict[str, Any]:
    """A model this job's Modelpin didn't report back: unknown, never safe, with no facts."""
    return {
        "id": model_id,
        "known": False,
        "status": None,
        "effective_status": None,
        "deprecated_at": None,
        "retired_at": None,
        "days_remaining": None,
        "affected": False,
        "replacement_id": None,
        "replacement_provider": None,
        "source_url": None,
        "fetched_at": None,
        "has_baseline": False,
        "check_command": None,
        "sources": ["scan"],
        "role": "app",
        "notes": None,
        "code_refs": [],
        "history_keys": [],
    }


def rebuilt(event: dict[str, Any], models: list[tuple[str, list[str]]], facts: dict[str, dict[str, Any]],
            payload: dict[str, Any] | None) -> dict[str, Any]:
    """The scan to send: the scan job's envelope and file paths, this job's facts, no work item keys."""
    source = event["source"]
    out: dict[str, Any] = {k: event.get(k) for k in EVENT_FIELDS}
    out["sample"] = False
    out["source"] = {k: source.get(k) for k in SOURCE_FIELDS}
    branch = out["source"].get("branch")
    out["source"]["branch"] = branch if isinstance(branch, str) and BRANCH.fullmatch(branch) else None
    out["source"].update(jira_keys=[], code_refs=[], history_keys=[])
    out["check"] = None
    rows = []
    for model_id, refs in models:
        row = dict(facts.get(model_id) or unknown_row(model_id))
        row.update(sources=["scan"], code_refs=refs, history_keys=[])
        rows.append(row)
    out["watch"] = {
        "registry_newest_fetched_at": payload["registry_newest_fetched_at"] if payload else None,
        # Modelpin's own exit code for these IDs; with none found, its "nothing declared" code.
        "exit_code": payload["exit_code"] if payload else 4,
        "models": rows,
    }
    out["truncated"] = []
    return out


def read_event(path: Path) -> Any:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
        raise Refused("the scan job left no event")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise Refused("the scan job's event isn't JSON") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, type=Path)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args(argv)
    url = os.environ.get("MODELPIN_WEBHOOK_URL", "").strip()
    key = os.environ.get("MODELPIN_WEBHOOK_SECRET", "").strip()
    if not url.startswith("https://") or not key:
        print("::error::Not sent: the ticket's address or key is missing.")
        return 1
    try:
        event = read_event(args.event)
        models = found(event, args.repo)
        facts, payload = registry_facts([m for m, _ in models]) if models else ({}, None)
        body = fit(rebuilt(event, models, facts, payload))
    except Refused as why:
        print(f"::error::Not sent: {why}.")
        return 1
    except (EventTooLarge, subprocess.TimeoutExpired):
        print("::error::Not sent: the scan is too large to look up or for Jira to take.")
        return 1
    result = send_event(url, key, body)
    answer = f"HTTP {result.status}" if result.status is not None else (result.error or "no response")
    if result.app_status:
        answer += f" {result.app_status}"
    if result.ok:
        print(f"Scan sent to Jira: {len(models)} model{'' if len(models) == 1 else 's'}, {answer}.")
        return 0
    print(f"::error::Jira didn't accept the scan: {answer}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
