// Run with: node --test .github/live/open-ticket.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { openTicket, refusal, signingKey } from "./open-ticket.mjs";

// The same strings are in modelpin-atlassian's apps/jira/tests/live.test.ts, which checks that Modelpin for Jira
// seals and signs exactly this. A test secret, used nowhere else.
const SECRET = "test-secret-not-used-anywhere";
const TICKET = {
  u: "https://0f0e0d0c-0000-4000-8000-000000000000.webtrigger.atlassian.app/public/abcDEF123",
  r: "a".repeat(32),
  b: "main",
  m: "claude-sonnet-5-5",
  x: 1794213000,
};
const SEALED =
  "v1.BwcHBwcHBwcHBwcHk31SB7YjKhO4mly8PmlnI6lxdSVFQ-PDEhNbbr-FRkeVXmyfhA5JpYvevdaM-PeVg4aWgaid1nDKWpITNl8EsEZCuVuw2oe3lVyz2kgXc6Wk9NWQPNrwGn6aghCtKoeRA4wzhGbAEpqgTB1ggc7fy0jLPduCGkIQToLDQUhaYHuCRFhdZ2petU5274maza8fBBw6DU5wk3jk_Kuplppvp5ujBXV4wlz1fEXTuXRKdtmXwUNeasfuZ-yIy4179ZPDinmwkwcs6w";
const BEFORE = { branch: "main", nowSeconds: TICKET.x - 60 };

test("opens Modelpin for Jira's ticket and derives the same signing key", () => {
  assert.deepEqual(openTicket(SECRET, SEALED), TICKET);
  assert.equal(signingKey(SECRET, TICKET.r), "92951197e543788143839e62be87c66b40b279cabc201d028a79a973f11e64a6");
  assert.equal(refusal(TICKET, BEFORE), null);
});

test("refuses a ticket sealed with another secret, or changed", () => {
  assert.equal(openTicket("another-secret", SEALED), null);
  const raw = Buffer.from(SEALED.slice(3), "base64url");
  raw[30] ^= 1;
  assert.equal(openTicket(SECRET, `v1.${raw.toString("base64url")}`), null);
  assert.match(refusal(null, BEFORE), /sealed/);
});

test("runs only what the ticket asks for, while it is open", () => {
  assert.match(refusal(TICKET, { branch: "fixed-prompt", nowSeconds: BEFORE.nowSeconds }), /branch/);
  assert.match(refusal(TICKET, { branch: "main", nowSeconds: TICKET.x }), /over/);
  assert.match(refusal({ ...TICKET, m: "gpt-4o" }, BEFORE), /model/);
  assert.match(refusal({ ...TICKET, u: "https://example.com/public/x" }, BEFORE), /web trigger/);
  assert.match(refusal({ ...TICKET, u: "http://a.webtrigger.atlassian.app/public/x" }, BEFORE), /web trigger/);
  assert.match(refusal({ ...TICKET, r: "zz" }, BEFORE), /request/);
});
