"""The bot's tool loop, with a stand-in for the Claude client. No network calls."""

import json
import unittest
from dataclasses import asdict, dataclass, field
from typing import Any

from app import bot


@dataclass
class Block:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None

    def model_dump(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Response:
    content: list[Block]


@dataclass
class Messages:
    responses: list[Response]
    requests: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **request: Any) -> Response:
        self.requests.append(json.loads(json.dumps(request, default=lambda block: block.model_dump())))
        return self.responses.pop(0)


@dataclass
class Client:
    messages: Messages


class ToolLoop(unittest.TestCase):
    def test_runs_the_tool_and_returns_the_answer(self) -> None:
        client = Client(
            Messages(
                [
                    Response([Block("tool_use", id="toolu_1", name="lookup_order", input={"order_id": "A-2041"})]),
                    Response([Block("text", text="Your tent was delivered on 30 October.")]),
                ]
            )
        )
        answer = bot.reply("dana.reyes@example.com", "Where is order A-2041?", client=client)  # type: ignore[arg-type]
        self.assertEqual(answer, "Your tent was delivered on 30 October.")
        first, second = client.messages.requests
        self.assertEqual(first["model"], bot.model_id())
        self.assertEqual(first["max_tokens"], bot.MAX_TOKENS)
        self.assertEqual([t["name"] for t in first["tools"]][0], "lookup_order")
        result = second["messages"][2]["content"][0]
        self.assertEqual(result["type"], "tool_result")
        self.assertEqual(result["tool_use_id"], "toolu_1")
        self.assertEqual(json.loads(result["content"])["order_id"], "A-2041")

    def test_status_card_refuses_a_bad_order_id(self) -> None:
        with self.assertRaises(ValueError):
            bot.status_card("1; drop table", client=Client(Messages([])))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
