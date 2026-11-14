"""Tests for scan_result.py: python -m unittest discover -s .github/live -p "test_*.py" """

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import scan_result

# What Modelpin 0.5.3 printed for a scan that found nothing (recorded 14 Nov 2026, exit code 4).
NOTHING = "error: no models declared: set `models:` in modelpin.yaml, or pass --scan to \nread them from the source\n"


class ResultTest(unittest.TestCase):
    def test_keeps_modelpins_json_as_it_is(self) -> None:
        doc = {"modelpin_version": "0.5.3", "exit_code": 1, "models": [{"id": "o3-2025-04-16"}], "notes": []}
        self.assertEqual(scan_result.result(json.dumps(doc), 1), doc)

    def test_nothing_found_is_an_empty_scan_with_exit_code_4(self) -> None:
        doc = scan_result.result(NOTHING, 4)
        assert doc is not None
        self.assertEqual((doc["exit_code"], doc["models"]), (4, []))

    def test_anything_else_is_no_result(self) -> None:
        self.assertIsNone(scan_result.result(NOTHING, 1))
        self.assertIsNone(scan_result.result("error: the registry could not be read", 4))
        self.assertIsNone(scan_result.result("Traceback (most recent call last):", 1))
        self.assertIsNone(scan_result.result("", 4))
        self.assertIsNone(scan_result.result('{"models": "all"}', 1))


class MainTest(unittest.TestCase):
    def run_main(self, text: str, code: int) -> tuple[int, str, object]:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "watch.txt"
            written = Path(tmp) / "watch.json"
            output.write_text(text, encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                status = scan_result.main(
                    ["--output", str(output), "--exit-code", str(code), "--write", str(written)]
                )
            doc = json.loads(written.read_text(encoding="utf-8")) if written.exists() else None
        return status, out.getvalue(), doc

    def test_writes_the_file_the_relay_reads(self) -> None:
        status, printed, doc = self.run_main(NOTHING, 4)
        self.assertEqual(status, 0)
        self.assertEqual(printed.strip(), "Modelpin's scan: 0 models, exit code 4.")
        self.assertEqual(doc["models"], [])  # type: ignore[index]

    def test_fails_the_step_and_writes_nothing_when_modelpin_didnt_finish(self) -> None:
        status, printed, doc = self.run_main("Killed", 137)
        self.assertEqual((status, doc), (1, None))
        self.assertIn("didn't finish (exit code 137)", printed)


if __name__ == "__main__":
    unittest.main()
