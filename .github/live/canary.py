"""The live check's daily canary: catches what would break a judge's live check before a judge does.

Runs on a schedule from .github/workflows/modelpin-canary.yml (QUALITY_REVIEW_3 section 7, "a January canary").
It checks, and prints one line per check, never a model's reply:

- the pinned install worked: Modelpin and its relay report the versions the live check pins;
- the recorded baseline is in the repository, readable, for the old model, with every scenario in scenarios/;
- each replacement a Jira admin can choose still answers on Anthropic's API (one request each, at most 1 output
  token), so a revoked key, used-up credit or a withdrawn model shows here;
- the production start page answers: one request with a ticket that can't open, which it refuses with HTTP 400 before
  it reads its storage or calls GitHub, and only once its demo secret and GitHub token are set (QUALITY_REVIEW_5, G2).
  Its address is the START_PAGE_URL secret and is never printed; with no secret the check is skipped and says so.

It exits 1 when any check fails, so GitHub marks the run failed and emails the repository's owner. It sends nothing
to any Jira site and needs no ticket.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from importlib import metadata
from pathlib import Path

OLD_MODEL = "claude-sonnet-4-5-20250929"
# The replacements Modelpin for Jira offers (apps/jira/src/domain/live.ts, LIVE_REPLACEMENTS).
REPLACEMENTS = ("claude-sonnet-5-5", "claude-sonnet-5", "claude-sonnet-4-6")
PINNED = {"modelpin": "0.5.3", "modelpin-relay": "0.1.1"}

Check = tuple[bool, str]


def versions(read: Callable[[str], str] = metadata.version) -> list[Check]:
    out: list[Check] = []
    for name, want in PINNED.items():
        try:
            got = read(name)
        except metadata.PackageNotFoundError:
            out.append((False, f"{name} isn't installed."))
            continue
        out.append((got == want, f"{name} {got}" + ("" if got == want else f", expected {want}.")))
    return out


def baseline(root: Path) -> list[Check]:
    path = root / ".modelpin" / f"baseline-{OLD_MODEL}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [(False, f"The baseline for {OLD_MODEL} can't be read ({type(error).__name__}).")]
    model = data.get("model_id") if isinstance(data, dict) else None
    recorded = data.get("scenarios") if isinstance(data, dict) else None
    if model != OLD_MODEL or not isinstance(recorded, dict):
        return [(False, f"The baseline file isn't {OLD_MODEL}'s recorded runs.")]
    wanted = sorted(p.stem for p in (root / "scenarios").glob("*.json"))
    missing = [s for s in wanted if s not in recorded]
    if not wanted or missing:
        return [(False, f"The baseline has no recorded runs for: {', '.join(missing) or 'any scenario'}.")]
    return [(True, f"The baseline for {OLD_MODEL} covers all {len(wanted)} scenarios.")]


def replacements(ask: Callable[[str], None], models: Iterable[str] = REPLACEMENTS) -> list[Check]:
    """`ask(model)` sends one request and raises on any refusal; only the error's type and status are printed."""
    out: list[Check] = []
    for model in models:
        try:
            ask(model)
            out.append((True, f"{model} answers on Anthropic's API."))
        except Exception as error:  # noqa: BLE001 - every failure is reported, none is fatal to the other checks
            status = getattr(error, "status_code", None)
            detail = f"HTTP {status}, " if isinstance(status, int) else ""
            out.append((False, f"{model} didn't answer ({detail}{type(error).__name__})."))
    return out


# A ticket the start page can't open: base64url characters, far too short to hold a sealed ticket.
PROBE_TICKET = "v1.canary"


def start_page(get: Callable[[str], int], url: str | None) -> list[Check]:
    """`get(url)` answers the HTTP status. Neither the address nor an error's message is printed, only its type."""
    if not url:
        return [(True, "The start page: not checked (no START_PAGE_URL secret).")]
    try:
        status = get(f"{url}?t={PROBE_TICKET}")
    except Exception as error:  # noqa: BLE001 - reported as a failed check, like the others
        return [(False, f"The start page didn't answer ({type(error).__name__}).")]
    if status == 400:
        return [(True, "The start page answers, with its secret and GitHub token set (400 for a ticket that can't open).")]
    if status == 503:
        return [(False, "The start page answers 503: its demo secret or GitHub token isn't set.")]
    return [(False, f"The start page answered HTTP {status}, expected 400 for a ticket that can't open.")]


def http_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # our own https address, from a secret
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def report(checks: list[Check]) -> int:
    for ok, line in checks:
        print(("ok    " if ok else "FAIL  ") + line)
    failed = sum(1 for ok, _ in checks if not ok)
    print(f"{len(checks) - failed} of {len(checks)} checks passed.")
    return 1 if failed else 0


def main() -> int:
    import anthropic

    client = anthropic.Anthropic()

    def ask(model: str) -> None:
        client.messages.create(model=model, max_tokens=1, messages=[{"role": "user", "content": "Hi"}])

    root = Path(__file__).resolve().parents[2]
    probe = start_page(http_status, os.environ.get("START_PAGE_URL") or None)
    return report(versions() + baseline(root) + replacements(ask) + probe)


if __name__ == "__main__":
    sys.exit(main())
