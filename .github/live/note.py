"""Says on the GitHub run what Modelpin found: one annotation and a job summary, with verdict counts and scenario
names only. It never prints a model's reply or Modelpin's explanation.

Modelpin ends with exit code 1 when it confirms a regression, which is how it blocks a merge, so GitHub shows the
run as failed. Without this note the run page says only "Process completed with exit code 1".

It reads the run record the check just wrote, by modelpin-relay's rule: the newest .modelpin/runs/check-*.json
written since the check started, for the same replacement and the same exit code. It never fails the run.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# The exact text Modelpin 0.5.3 adds to a regression that came back on a second set of runs (modelpin-relay
# checks it against the installed Modelpin).
CONFIRMED_NOTE = "reproduced on a second set of candidate runs, scored on its own"
ORDER = ("regression", "changed_minor", "insufficient_evidence", "unchanged")
LABELS = {
    "regression": "Regression",
    "changed_minor": "Minor change",
    "insufficient_evidence": "Couldn't measure",
    "unchanged": "Unchanged",
}
# Modelpin's scenario loader: every .json under scenarios/, minus these names and folders, and dot-folders.
RESERVED_FILES = {"manifest.json", "roles.json", "labels.json"}
RESERVED_DIRS = {"results", "__pycache__"}


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def fresh_record(store: Path, since: float, to_model: str, exit_code: int) -> dict | None:
    newest = None
    runs = store / "runs"
    for path in runs.glob("check-*.json") if runs.is_dir() else []:
        if path.is_symlink() or not path.is_file():
            continue
        mtime = path.stat().st_mtime
        if mtime < since:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("to_model") != to_model:
            continue
        if data.get("exit_code") != exit_code or isinstance(data.get("exit_code"), bool):
            continue
        if newest is None or (mtime, path.name) > newest[0]:
            newest = ((mtime, path.name), data)
    return newest[1] if newest else None


def scenario_ids(directory: Path) -> set[str]:
    found = set()
    for path in directory.rglob("*.json") if directory.is_dir() else []:
        parents = path.relative_to(directory).parts[:-1]
        if path.name in RESERVED_FILES or any(p in RESERVED_DIRS or p.startswith(".") for p in parents):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str) and data["id"]:
            found.add(data["id"])
    return found


def note(record: dict | None, scenarios: set[str], to_model: str, exit_code: int) -> tuple[str, str, str]:
    """The annotation's level and title, and the summary's Markdown. Its first line is also the annotation."""
    results = []
    for raw in record.get("results", []) if record else []:
        if isinstance(raw, dict) and raw.get("verdict") in ORDER and isinstance(raw.get("scenario_id"), str):
            results.append(raw)
    results.sort(key=lambda r: (ORDER.index(r["verdict"]), r["scenario_id"]))
    counts = {v: sum(r["verdict"] == v for r in results) for v in ORDER}
    not_compared = sorted(scenarios - {r["scenario_id"] for r in results})
    missing = counts["insufficient_evidence"] + len(not_compared)
    measured = len(results) - counts["insufficient_evidence"]
    more = f" Modelpin couldn't measure {plural(missing, 'other scenario')}." if missing else ""
    regressed = [r for r in results if r["verdict"] == "regression"]

    def confirmed(r: dict) -> bool:
        words = r.get("explanation")
        return isinstance(words, str) and CONFIRMED_NOTE in words

    if record is not None and exit_code == 1 and regressed:
        each = ", each" if len(regressed) > 1 else ""
        seconds = f"{each} confirmed on a second set of runs" if all(map(confirmed, regressed)) else ""
        names = ", ".join(r["scenario_id"] for r in regressed)
        level, title = "error", f"Modelpin found {plural(len(regressed), 'regression')}"
        head = (
            f"{len(regressed)} of {plural(measured, 'scenario')} regressed moving to {to_model}{seconds}: "
            f"{names}.{more} Modelpin ends with exit code 1 when it confirms a regression, which is how it blocks "
            "a merge, so GitHub shows this run as failed."
        )
    elif record is not None and exit_code == 0 and not missing:
        minor = counts["changed_minor"]
        level, title = "notice", "Modelpin found no regression"
        head = f"No regression on {plural(measured, 'scenario')} moving to {to_model}" + (
            f" ({plural(minor, 'minor change')})." if minor else "."
        )
    elif exit_code == 3 or (exit_code == 0 and record is not None):
        level, title = "warning", "Modelpin couldn't measure every scenario"
        head = (
            f"Modelpin couldn't measure {missing} of {plural(len(results) + len(not_compared), 'scenario')} "
            f"moving to {to_model}, so it can't say whether {to_model} behaves the same."
            if results and missing
            else f"Modelpin couldn't compare any scenario moving to {to_model}, so this check has no result."
        )
    else:
        level, title = "warning", "Modelpin didn't finish the check"
        head = f"Modelpin didn't finish the check (exit code {exit_code}), so nothing about {to_model} was measured."

    lines = ["### Modelpin live check", "", head, ""]
    if results or not_compared:
        lines += ["| Scenario | Verdict |", "| --- | --- |"]
        for r in results:
            label = LABELS[r["verdict"]]
            if r["verdict"] == "regression" and confirmed(r):
                label += ", confirmed on a second set of runs"
            lines.append(f"| `{r['scenario_id']}` | {label} |")
        lines += [f"| `{s}` | Not compared |" for s in not_compared]
        lines.append("")
    source = record.get("from_model") if record and isinstance(record.get("from_model"), str) else None
    if source:
        lines.append(f"Compared with the runs of {source} recorded on 12 Nov 2026.")
    lines.append("Each scenario's evidence is in Jira, on the work item this live check opened.")
    return level, title, "\n".join(lines) + "\n"


def command_text(text: str, *, prop: bool = False) -> str:
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", type=float, required=True)
    parser.add_argument("--to", required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--store-dir", type=Path, default=Path(".modelpin"))
    parser.add_argument("--scenarios-dir", type=Path, default=Path("scenarios"))
    args = parser.parse_args()
    record = fresh_record(args.store_dir, args.since, args.to, args.exit_code)
    level, title, summary = note(record, scenario_ids(args.scenarios_dir), args.to, args.exit_code)
    head = summary.splitlines()[2]
    print(f"Note on this run: {head}")
    print(f"::{level} title={command_text(title, prop=True)}::{command_text(head)}")
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as out:
            out.write(summary)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - a note must never change the check's result
        print(f"Couldn't write the note on this run ({type(error).__name__}).", file=sys.stderr)
