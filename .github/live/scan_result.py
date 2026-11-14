"""Turns `modelpin watch --scan --json` output into the file modelpin-relay reads, for a repository scan.

Modelpin 0.5.3 answers a scan that found no model ID with exit code 4 and one sentence instead of JSON ("error: no
models declared: ..."), since the scan config declares none. That is a real result here, "Modelpin found no model
IDs in this repository", so this writes Modelpin's own JSON shape with no models and exit code 4, which Jira shows
as exactly that. Any other output that isn't Modelpin's JSON (an unreadable registry, a crash) fails the step, so
Jira is never told a repository has no models when Modelpin didn't say so.

    python .github/live/scan_result.py --output <watch output> --exit-code <code> --write <file for the relay>
"""

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

NOTHING_FOUND = "error: no models declared"
MAX_BYTES = 20_000_000


def modelpin_version() -> str | None:
    try:
        return version("modelpin")
    except PackageNotFoundError:
        return None


def result(text: str, exit_code: int) -> dict | None:
    """Modelpin's JSON as it is, the empty scan for "nothing found", or None for anything else."""
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    if isinstance(doc, dict) and isinstance(doc.get("models"), list):
        return doc
    if exit_code == 4 and text.strip().lower().startswith(NOTHING_FOUND):
        return {"modelpin_version": modelpin_version(), "exit_code": 4, "registry": None, "models": [], "notes": []}
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--write", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output.stat().st_size > MAX_BYTES:
            raise ValueError("too large")
        text = args.output.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        print("::error::Modelpin's scan left no readable output, so nothing is sent.")
        return 1
    doc = result(text, args.exit_code)
    if doc is None:
        print(f"::error::Modelpin's scan didn't finish (exit code {args.exit_code}), so nothing is sent.")
        return 1
    args.write.write_text(json.dumps(doc), encoding="utf-8")
    models = len(doc["models"])
    print(f"Modelpin's scan: {models} model{'' if models == 1 else 's'}, exit code {args.exit_code}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
