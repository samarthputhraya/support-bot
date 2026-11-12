"""Asks Anthropic's API once whether it still serves the model the bot was built on, and says so in the log.

Anthropic retires claude-sonnet-4-5-20250929 on 30 Nov 2026. Before then the call is answered; after it, the API
refuses the model. Either way the check compares the replacement with the baseline recorded on 12 Nov 2026.
Prints the status only, never a reply, and never fails the run.
"""

import anthropic

MODEL = "claude-sonnet-4-5-20250929"

try:
    anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=1, messages=[{"role": "user", "content": "Hi"}]
    )
    print(f"{MODEL} still answers on Anthropic's API. Anthropic retires it on 30 Nov 2026.")
except anthropic.APIStatusError as error:
    body = error.body if isinstance(error.body, dict) else {}
    detail = body.get("error") if isinstance(body.get("error"), dict) else {}
    kind = detail.get("type") if isinstance(detail.get("type"), str) else None
    print(f"Anthropic's API refused {MODEL}: HTTP {error.status_code}{f', {kind}' if kind else ''}.")
except Exception as error:  # noqa: BLE001 - this step only reports; the check below still runs
    print(f"Couldn't ask Anthropic's API about {MODEL} ({type(error).__name__}).")
print(f"The check compares the replacement with {MODEL}'s baseline, recorded on 12 Nov 2026.")
