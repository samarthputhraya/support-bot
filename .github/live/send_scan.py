"""Sends a repository scan to the one Jira site its ticket names, signed for that one request.

The workflow's scan job read the named repository's files, which this job never sees; it hands over one event.json
built by `modelpin-relay publish-watch --ci local`. That job held no secret, so its event is checked here before it
is signed: one scan (a watch event), of exactly the repository the ticket names, from the relay's own schema. Then
it is rebuilt from the fields a scan sends, with no work item keys: a repository's branch names and commit messages
come from its own committers, and must never point at a work item on the judge's site. The address and the key come
from this job's own opening of the ticket.

It prints only the outcome, never the event, the address or the key.

    python .github/live/send_scan.py --event <event.json> --repo <owner/name>
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from modelpin_relay.payload import MAX_WATCH_MODELS, SCHEMA_ID
from modelpin_relay.transport import send_event
from modelpin_relay.truncate import EventTooLarge, fit

MAX_FILE_BYTES = 2_000_000
SOURCE_FIELDS = ("ci", "repo_key", "repo_url", "commit", "branch", "pr_id", "pr_url", "build_url", "build_number")
EVENT_FIELDS = ("schema", "event_id", "kind", "sent_at", "relay_version", "modelpin_version")


class Refused(Exception):
    """The event isn't a scan of the ticket's repository; nothing is sent."""


def checked(event: Any, repo: str) -> dict[str, Any]:
    """The scan to send, rebuilt from what a scan sends, or Refused with the reason."""
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
    if not all(isinstance(m, dict) for m in models):
        raise Refused("the scan job's event isn't a scan")
    out: dict[str, Any] = {k: event.get(k) for k in EVENT_FIELDS}
    out["sample"] = False
    out["source"] = {k: source.get(k) for k in SOURCE_FIELDS}
    # File paths stay: they say where in the repository each model ID is. Work item keys never do.
    out["source"].update(jira_keys=[], code_refs=[], history_keys=[])
    out["check"] = None
    out["watch"] = {
        "registry_newest_fetched_at": watch.get("registry_newest_fetched_at"),
        "exit_code": watch.get("exit_code"),
        "models": [{**m, "history_keys": []} for m in models],
    }
    out["truncated"] = [t for t in event.get("truncated", []) if t != "history_keys"] if isinstance(
        event.get("truncated"), list
    ) else []
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
        event = checked(read_event(args.event), args.repo)
        body = fit(event)
    except Refused as why:
        print(f"::error::Not sent: {why}.")
        return 1
    except EventTooLarge:
        print("::error::Not sent: the scan is too large for Jira to take.")
        return 1
    result = send_event(url, key, body)
    answer = f"HTTP {result.status}" if result.status is not None else (result.error or "no response")
    if result.app_status:
        answer += f" {result.app_status}"
    models = len(event["watch"]["models"])
    if result.ok:
        print(f"Scan sent to Jira: {models} model{'' if models == 1 else 's'}, {answer}.")
        return 0
    print(f"::error::Jira didn't accept the scan: {answer}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
