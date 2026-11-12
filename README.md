# support-bot

A small customer support bot for an online outdoor-gear shop. It answers a signed-in customer
with one LLM and six tools: look up an order, refund it, change its shipping address, hand the
chat to a person, open a ticket, and read a help article. It also writes the JSON order status
card for the shop's website.

The bot is a public demo for [Modelpin](https://pypi.org/project/modelpin/), which checks a model
switch against recorded behaviour, and for Modelpin for Jira, which shows the result on the
model's migration work item. It is the Claude copy of the support bot in Modelpin for Jira's
other demo, which runs on OpenAI models: the same shop, tools, prompts and scenarios.

## The model, and why it matters

The bot uses `claude-sonnet-4-5-20250929`. Anthropic retires it on the Claude API on 30 Nov 2026
and names `claude-sonnet-5-5` as its replacement
([Anthropic's model deprecations page](https://platform.claude.com/docs/en/about-claude/model-deprecations),
read 12 Nov 2026). After that date the old model can't be called, so how it behaved can only be
recorded before then. The baseline in `.modelpin/` is that recording.

## Layout

| Path                             | What it is                                                                          |
| -------------------------------- | ----------------------------------------------------------------------------------- |
| `app/model.txt`                  | The model id the bot uses. Switching models is a one-line change here.              |
| `app/prompts.py`, `app/tools.py` | The prompts and tool definitions sent to the model.                                 |
| `app/bot.py`                     | The chat loop: calls the model, runs its tool calls, returns the answer.            |
| `app/shop.py`                    | The shop's orders, refund rules and support queue, in memory for now.               |
| `tests/`                         | Unit tests: `python -m unittest discover -s tests`. They make no model calls.       |
| `modelpin.yaml`                  | Modelpin's settings: the current model, the provider and 5 runs per scenario.       |
| `scenarios/`                     | Eight conversations the bot must keep handling the same way, as Modelpin scenarios. |
| `.modelpin/`                     | The recorded baseline that Modelpin compares a new model against.                   |

## Branches

| Branch         | Prompt                                                                                                                                                                            |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `main`         | The support prompt as first written.                                                                                                                                              |
| `fixed-prompt` | Two rules made stricter: look an order up only when its details are needed, and never one the customer says is someone else's; hand over to a person only if the customer agrees. |

Each branch has its own baseline, because the scenarios carry the branch's prompt.

## Scenarios

Each scenario uses the bot's real prompt and tools, with a fixed customer and date
(`tests/test_scenarios.py` checks this). Two of them give the model more than the app's tools
now return, on purpose: `other_customer_data` hands it another customer's order and
`order_summary_json` the full order record. The app blocks both in code (`app/shop.py`); the
scenarios check that a new model still follows the prompt's rules if a tool ever returns too much.

| Scenario                | What it checks                                                           |
| ----------------------- | ------------------------------------------------------------------------ |
| `refund_flow`           | A damaged order inside the refund window: look it up, then refund it     |
| `address_change`        | An order still processing: look it up, then change the address           |
| `refund_outside_window` | A refund asked 58 days after delivery: no refund, offer a person instead |
| `other_customer_data`   | Someone else's order: decline, and never reveal its address              |
| `order_summary_json`    | The status card: only a JSON object with three keys, no code fence       |
| `escalate_or_ticket`    | An angry customer who asks for a person                                  |
| `policy_question`       | A returns question about one order: read the help article                |
| `simple_greeting`       | A thank-you message: no tool call at all                                 |

Modelpin never runs the tools: each scenario carries the result every tool call gets, so only
the model varies between runs. No semantic judge is configured, so Modelpin compares tool calls,
refusals and each scenario's text checks, and every report says what it could not measure.

## Check a model switch yourself

With Python 3.11 or later and your own Anthropic API key in `ANTHROPIC_API_KEY`:

```bash
pip install "modelpin[providers]==0.5.3"
modelpin check --to claude-sonnet-5-5
```

Modelpin replays the eight scenarios 5 times on the new model and compares them with the baseline.
It fails only when a change is statistically significant, large enough to matter, and comes back
on a fresh set of runs.

## Live checks from Jira

`.github/workflows/modelpin-live.yml` runs when a Jira admin selects **Run a live check** in
Modelpin for Jira. Their browser opens a start page, which runs the workflow with a sealed ticket:
the Jira site's address for results, the request, the branch and the replacement model. Only this
repository's `MODELPIN_LIVE_SECRET` opens the ticket. The run reads it from its event payload, so the
log never shows it; it is good for 30 minutes, and a run refuses it with under 5 minutes left. The
address and the signing key it yields are masked, and only the two steps that send results to Jira
get them. Modelpin and its dependencies install at the exact versions in `.github/live/requirements.txt`,
the versions of the last good live check. The run:

1. asks Anthropic's API once whether it still serves `claude-sonnet-4-5-20250929` (the status only);
2. scans the repository with `modelpin watch` and sends the result to that Jira site, where it opens
   a work item marked [Live demo];
3. checks the replacement with `modelpin check` and sends the evidence to the same work item.

The workflow's tests: `node --test .github/live/open-ticket.test.mjs`.

## Licence

Apache-2.0. See `LICENSE`.
