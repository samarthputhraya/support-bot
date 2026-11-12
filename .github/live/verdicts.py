"""Prints one line for a repeat check, for "N of M checks agree" in Modelpin for Jira: the exit code, each
scenario's verdict (and whether Modelpin confirmed a regression on a second set of runs) and the candidate runs'
token totals. It never prints a model's reply or Modelpin's explanation, and never fails the run.
"""

import argparse
import re
import sys
from pathlib import Path

from note import CONFIRMED_NOTE, ORDER, fresh_record

SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


def count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def line(record: dict | None, exit_code: int) -> str:
    if record is None:
        return f"Verdicts: exit={exit_code} record=none"
    parts = [f"exit={exit_code}"]
    results = [r for r in record.get("results", []) if isinstance(r, dict)]
    for r in sorted(results, key=lambda r: str(r.get("scenario_id"))):
        scenario, verdict = r.get("scenario_id"), r.get("verdict")
        if not isinstance(scenario, str) or not SAFE_ID.match(scenario) or verdict not in ORDER:
            parts.append("unreadable=result")
            continue
        words = r.get("explanation")
        confirmed = verdict == "regression" and isinstance(words, str) and CONFIRMED_NOTE in words
        parts.append(f"{scenario}={verdict}{':confirmed' if confirmed else ''}")
    tokens_in = tokens_out = 0
    runs = record.get("candidate_runs")
    for traces in runs.values() if isinstance(runs, dict) else []:
        for trace in traces if isinstance(traces, list) else []:
            if isinstance(trace, dict):
                tokens_in += count(trace.get("tokens_in"))
                tokens_out += count(trace.get("tokens_out"))
    parts.append(f"tokens_in={tokens_in} tokens_out={tokens_out}")
    return "Verdicts: " + " ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", type=float, required=True)
    parser.add_argument("--to", required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--store-dir", type=Path, default=Path(".modelpin"))
    args = parser.parse_args()
    print(line(fresh_record(args.store_dir, args.since, args.to, args.exit_code), args.exit_code))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - a repeat check's line must never stop the next one
        print(f"Couldn't read this check's verdicts ({type(error).__name__}).", file=sys.stderr)
