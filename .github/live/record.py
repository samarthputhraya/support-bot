"""Records, once a day around its retirement, whether Anthropic's API still serves the model the demo bot was built on.

Anthropic retires claude-sonnet-4-5-20250929 on 30 Nov 2026 (its deprecations page, which called the date tentative
when read on 15 Nov 2026). From .github/workflows/modelpin-retirement-record.yml, each day from 28 Nov to 3 Dec
2026 (UTC) this asks once, with at most 1 output token, and appends one line to retirement-record.jsonl: when, the
model, whether it answered, the HTTP status and the error's type, and the run that asked. Never a reply, a message
or a key. Modelpin for Jira shows these lines on the live demo's model once the day has passed, so a judge in January
sees what happened on the day, with the public run to check it against.

Outside the window a scheduled run records nothing; a run started by hand always records (a dated line before the
date shows the model still answering).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

MODEL = "claude-sonnet-4-5-20250929"
FIRST_DAY = date(2026, 11, 28)
LAST_DAY = date(2026, 12, 3)
RECORD = Path(__file__).resolve().parent / "retirement-record.jsonl"


def should_record(event: str, today: date) -> bool:
    return event != "schedule" or FIRST_DAY <= today <= LAST_DAY


def outcome(ask: Callable[[], None]) -> dict[str, Any]:
    """`ask()` sends the one request. Only the status and the error's type are kept, never a reply or a message."""
    try:
        ask()
        return {"answered": True, "status": 200, "error_type": None}
    except Exception as error:  # noqa: BLE001 - every outcome is a fact to record
        status = getattr(error, "status_code", None)
        body = getattr(error, "body", None)
        detail = body.get("error") if isinstance(body, dict) else None
        kind = detail.get("type") if isinstance(detail, dict) else None
        return {
            "answered": False,
            "status": status if isinstance(status, int) else None,
            "error_type": kind if isinstance(kind, str) else type(error).__name__,
        }


def append(path: Path, at: str, result: Mapping[str, Any], env: Mapping[str, str]) -> None:
    run_id = env.get("GITHUB_RUN_ID") or None
    server = env.get("GITHUB_SERVER_URL")
    repository = env.get("GITHUB_REPOSITORY")
    run_url = f"{server}/{repository}/actions/runs/{run_id}" if run_id and server and repository else None
    line = {
        "at": at,
        "model": MODEL,
        "answered": result["answered"],
        "status": result["status"],
        "error_type": result["error_type"],
        "run_id": run_id,
        "run_url": run_url,
    }
    with path.open("a", encoding="utf-8", newline="\n") as out:
        out.write(json.dumps(line) + "\n")


def main() -> int:
    now = datetime.now(UTC)
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if not should_record(event, now.date()):
        print(f"Outside {FIRST_DAY} to {LAST_DAY} (UTC): nothing recorded.")
        return 0
    import anthropic

    client = anthropic.Anthropic()

    def ask() -> None:
        client.messages.create(model=MODEL, max_tokens=1, messages=[{"role": "user", "content": "Hi"}])

    result = outcome(ask)
    append(RECORD, now.strftime("%Y-%m-%dT%H:%M:%SZ"), result, os.environ)
    said = (
        "answered"
        if result["answered"]
        else f"was refused (HTTP {result['status']}, {result['error_type']})"
        if result["status"]
        else f"couldn't be reached ({result['error_type']})"
    )
    print(f"{now:%Y-%m-%d}: a request for {MODEL} {said}. Recorded in .github/live/{RECORD.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
