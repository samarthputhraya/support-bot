"""The scenarios carry the bot's real prompts and tools. Run with: python -m unittest discover -s tests"""

import json
import unittest
from pathlib import Path
from typing import Any

from app.prompts import STATUS_CARD_PROMPT, support_prompt
from app.tools import STATUS_CARD_TOOLS, SUPPORT_TOOLS

SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios"

#: The fixed customer and date every support scenario uses.
DANA = "dana.reyes@example.com"
SCENARIO_DATE = "2026-11-09"


def as_claude_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """A scenario's OpenAI-style function tool in the Messages API's form, as Modelpin sends it."""
    function = tool["function"]
    return {
        "name": function["name"],
        "description": function["description"],
        "input_schema": function["parameters"],
    }


class Scenarios(unittest.TestCase):
    def test_there_are_eight(self) -> None:
        self.assertEqual(len(list(SCENARIOS.glob("*.json"))), 8)

    def test_each_uses_the_bots_prompt_and_tools(self) -> None:
        for path in sorted(SCENARIOS.glob("*.json")):
            with self.subTest(scenario=path.stem):
                scenario = json.loads(path.read_text(encoding="utf-8"))
                system = scenario["input"]["messages"][0]
                tools = [as_claude_tool(t) for t in scenario["input"]["tools"]]
                self.assertEqual(system["role"], "system")
                if path.stem == "order_summary_json":
                    self.assertEqual(system["content"], STATUS_CARD_PROMPT)
                    self.assertEqual(tools, STATUS_CARD_TOOLS)
                else:
                    self.assertEqual(system["content"], support_prompt(DANA, SCENARIO_DATE))
                    self.assertEqual(tools, SUPPORT_TOOLS)


if __name__ == "__main__":
    unittest.main()
