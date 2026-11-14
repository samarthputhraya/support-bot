"""Tests for canary.py: python -m unittest discover -s .github/live -p "test_*.py" """

import contextlib
import io
import json
import tempfile
import unittest
from importlib import metadata
from pathlib import Path

from canary import OLD_MODEL, REPLACEMENTS, baseline, replacements, report, versions


class Refused(Exception):
    status_code = 404


def tree(scenarios: list[str], recorded: list[str] | None, model: str = OLD_MODEL) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "scenarios").mkdir()
    for s in scenarios:
        (root / "scenarios" / f"{s}.json").write_text("{}", encoding="utf-8")
    if recorded is not None:
        (root / ".modelpin").mkdir()
        body = {"model_id": model, "scenarios": {s: [] for s in recorded}, "fingerprints": {}}
        (root / ".modelpin" / f"baseline-{OLD_MODEL}.json").write_text(json.dumps(body), encoding="utf-8")
    return root


class CanaryTest(unittest.TestCase):
    def test_versions_pass_only_at_the_pinned_ones(self) -> None:
        pinned = {"modelpin": "0.5.3", "modelpin-relay": "0.1.1"}
        self.assertTrue(all(ok for ok, _ in versions(lambda n: pinned[n])))
        drifted = versions(lambda n: "0.5.4" if n == "modelpin" else pinned[n])
        self.assertEqual(drifted[0], (False, "modelpin 0.5.4, expected 0.5.3."))

        def missing(name: str) -> str:
            raise metadata.PackageNotFoundError(name)

        self.assertEqual(versions(missing)[0], (False, "modelpin isn't installed."))

    def test_baseline_must_cover_every_scenario(self) -> None:
        self.assertEqual(
            baseline(tree(["a", "b"], ["a", "b"])),
            [(True, f"The baseline for {OLD_MODEL} covers all 2 scenarios.")],
        )
        self.assertEqual(
            baseline(tree(["a", "b"], ["a"])),
            [(False, "The baseline has no recorded runs for: b.")],
        )
        self.assertFalse(baseline(tree(["a"], None))[0][0])
        self.assertFalse(baseline(tree(["a"], ["a"], model="another-model"))[0][0])

    def test_the_real_repository_baseline_holds(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.assertTrue(all(ok for ok, _ in baseline(root)))

    def test_each_replacement_is_asked_and_a_refusal_names_only_its_status(self) -> None:
        asked: list[str] = []

        def ask(model: str) -> None:
            asked.append(model)
            if model == "claude-sonnet-5":
                raise Refused("the model's own words would never be printed")

        checks = replacements(ask)
        self.assertEqual(asked, list(REPLACEMENTS))
        self.assertIn((False, "claude-sonnet-5 didn't answer (HTTP 404, Refused)."), checks)
        self.assertTrue(all("never be printed" not in line for _, line in checks))

    def test_report_fails_the_run_on_any_failed_check(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(report([(True, "a"), (False, "b")]), 1)
        self.assertIn("1 of 2 checks passed.", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(report([(True, "a")]), 0)


if __name__ == "__main__":
    unittest.main()
