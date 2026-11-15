// Run with: node --test .github/live/open-ticket.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createCipheriv, createHmac, randomBytes } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { MIN_SECONDS_LEFT, openTicket, refusal, sealedFromEvent, signingKey } from "./open-ticket.mjs";

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
// Ten of the ticket's 30 minutes left.
const BEFORE = { branch: "main", nowSeconds: TICKET.x - 600 };
const SCRIPT = fileURLToPath(new URL("./open-ticket.mjs", import.meta.url));

// Seals a ticket the way Modelpin for Jira does, for the end-to-end tests below.
function seal(secret, fields) {
  const key = createHmac("sha256", Buffer.from(secret, "utf8")).update("modelpin-live-seal-v1", "utf8").digest();
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(Buffer.from("modelpin-live-v1", "utf8"));
  const body = Buffer.concat([cipher.update(JSON.stringify(fields), "utf8"), cipher.final()]);
  return `v1.${Buffer.concat([iv, body, cipher.getAuthTag()]).toString("base64url")}`;
}

// Runs the step as GitHub would: the ticket only in the event payload, never in the environment.
function runStep(event) {
  const dir = mkdtempSync(join(tmpdir(), "open-ticket-"));
  try {
    const paths = { event: join(dir, "event.json"), output: join(dir, "output"), env: join(dir, "env") };
    writeFileSync(paths.event, JSON.stringify(event));
    writeFileSync(paths.output, "");
    writeFileSync(paths.env, "");
    const run = spawnSync(process.execPath, [SCRIPT], {
      encoding: "utf8",
      env: {
        PATH: process.env.PATH,
        MODELPIN_LIVE_SECRET: SECRET,
        GITHUB_EVENT_PATH: paths.event,
        GITHUB_OUTPUT: paths.output,
        GITHUB_ENV: paths.env,
        GITHUB_REF_NAME: "main",
      },
    });
    return {
      status: run.status,
      stdout: run.stdout,
      output: readFileSync(paths.output, "utf8"),
      env: readFileSync(paths.env, "utf8"),
    };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

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

test("runs a ticket for each of the three prompts only on its own branch", () => {
  const steps = { ...TICKET, b: "explicit-rules" };
  assert.equal(refusal(steps, { branch: "explicit-rules", nowSeconds: BEFORE.nowSeconds }), null);
  assert.match(refusal(steps, { branch: "main", nowSeconds: BEFORE.nowSeconds }), /branch/);
  assert.match(refusal({ ...TICKET, b: "explicit_rules" }, { branch: "explicit_rules", nowSeconds: BEFORE.nowSeconds }), /branch/);
});

test("runs only what the ticket asks for, while it is open", () => {
  assert.match(refusal(TICKET, { branch: "fixed-prompt", nowSeconds: BEFORE.nowSeconds }), /branch/);
  assert.match(refusal(TICKET, { branch: "main", nowSeconds: TICKET.x }), /over/);
  assert.match(refusal({ ...TICKET, m: "gpt-4o" }, BEFORE), /model/);
  assert.match(refusal({ ...TICKET, u: "https://example.com/public/x" }, BEFORE), /web trigger/);
  assert.match(refusal({ ...TICKET, u: "http://a.webtrigger.atlassian.app/public/x" }, BEFORE), /web trigger/);
  assert.match(refusal({ ...TICKET, r: "zz" }, BEFORE), /request/);
});

test("refuses a ticket with under 5 minutes left, too few to finish before Jira stops taking results", () => {
  assert.equal(MIN_SECONDS_LEFT, 300);
  assert.equal(refusal(TICKET, { branch: "main", nowSeconds: TICKET.x - 300 }), null);
  const late = refusal(TICKET, { branch: "main", nowSeconds: TICKET.x - 299 });
  assert.match(late, /under 5 of the live check's 30 minutes are left/);
  assert.match(late, /start a new one in Jira/);
  assert.match(refusal(TICKET, { branch: "main", nowSeconds: TICKET.x - 1 }), /under 5/);
  assert.match(refusal(TICKET, { branch: "main", nowSeconds: TICKET.x + 1 }), /over/);
});

test("reads the ticket from the event payload's workflow_dispatch input only", () => {
  assert.equal(sealedFromEvent({ inputs: { ticket: SEALED } }), SEALED);
  assert.equal(sealedFromEvent({ inputs: { ticket: 5 } }), "");
  assert.equal(sealedFromEvent({ inputs: {} }), "");
  assert.equal(sealedFromEvent({}), "");
  assert.equal(sealedFromEvent(null), "");
  assert.equal(sealedFromEvent("v1.abc"), "");
});

test("the step gives the address and key as masked step outputs, the model as env, and never prints the ticket", () => {
  const fields = { ...TICKET, x: Math.floor(Date.now() / 1000) + 1800 };
  const sealed = seal(SECRET, fields);
  const key = signingKey(SECRET, fields.r);
  const run = runStep({ inputs: { ticket: sealed } });
  assert.equal(run.status, 0, run.stdout);
  assert.equal(run.output, `url=${fields.u}\nkey=${key}\n`);
  assert.equal(run.env, `LIVE_MODEL=${fields.m}\n`);
  const lines = run.stdout.trim().split("\n");
  assert.deepEqual(lines, [
    `::add-mask::${fields.u}`,
    `::add-mask::${key}`,
    "Live check for one Jira site: main branch, claude-sonnet-4-5-20250929 against claude-sonnet-5-5.",
  ]);
  assert.ok(!run.stdout.includes(sealed));
});

test("the step refuses, and writes nothing, when the payload has no ticket or too little time is left", () => {
  const none = runStep({ inputs: {} });
  assert.equal(none.status, 1);
  assert.match(none.stdout, /::error::Not running: the ticket wasn't sealed/);
  assert.equal(none.output + none.env, "");

  const late = seal(SECRET, { ...TICKET, x: Math.floor(Date.now() / 1000) + 120 });
  const tooLate = runStep({ inputs: { ticket: late } });
  assert.equal(tooLate.status, 1);
  assert.match(tooLate.stdout, /::error::Not running: under 5 of the live check's 30 minutes are left/);
  assert.equal(tooLate.output + tooLate.env, "");
  assert.ok(!tooLate.stdout.includes(late));
});
