// Run with: node --test .github/live/open-scan.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createCipheriv, createHmac, randomBytes } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { signingKey } from "./open-ticket.mjs";
import { isScanRepo, refusal } from "./open-scan.mjs";

// A test secret, used nowhere else.
const SECRET = "test-secret-not-used-anywhere";
const SCAN = {
  u: "https://0f0e0d0c-0000-4000-8000-000000000000.webtrigger.atlassian.app/public/abcDEF123",
  r: "c".repeat(32),
  k: "scan",
  g: "acme-labs/help-desk",
  x: 1794213000,
};
const BEFORE = { nowSeconds: SCAN.x - 600 };
const SCRIPT = fileURLToPath(new URL("./open-scan.mjs", import.meta.url));

function seal(secret, fields) {
  const key = createHmac("sha256", Buffer.from(secret, "utf8")).update("modelpin-live-seal-v1", "utf8").digest();
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(Buffer.from("modelpin-live-v1", "utf8"));
  const body = Buffer.concat([cipher.update(JSON.stringify(fields), "utf8"), cipher.final()]);
  return `v1.${Buffer.concat([iv, body, cipher.getAuthTag()]).toString("base64url")}`;
}

function runStep(mode, event) {
  const dir = mkdtempSync(join(tmpdir(), "open-scan-"));
  try {
    const paths = { event: join(dir, "event.json"), output: join(dir, "output") };
    writeFileSync(paths.event, JSON.stringify(event));
    writeFileSync(paths.output, "");
    const run = spawnSync(process.execPath, [SCRIPT, mode], {
      encoding: "utf8",
      env: {
        PATH: process.env.PATH,
        MODELPIN_LIVE_SECRET: SECRET,
        GITHUB_EVENT_PATH: paths.event,
        GITHUB_OUTPUT: paths.output,
      },
    });
    return { status: run.status, stdout: run.stdout, output: readFileSync(paths.output, "utf8") };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("takes a scan's ticket while it is open, for one public GitHub repository", () => {
  assert.equal(refusal(SCAN, BEFORE), null);
  assert.match(refusal(null, BEFORE), /sealed/);
  assert.match(refusal({ ...SCAN, k: undefined }, BEFORE), /isn't a repository scan's/);
  assert.match(refusal({ ...SCAN, b: "main" }, BEFORE), /isn't a repository scan's/);
  assert.match(refusal({ ...SCAN, m: "claude-sonnet-5-5" }, BEFORE), /isn't a repository scan's/);
  assert.match(refusal({ ...SCAN, u: "https://example.com/public/x" }, BEFORE), /web trigger/);
  assert.match(refusal({ ...SCAN, r: "zz" }, BEFORE), /request/);
  assert.match(refusal({ ...SCAN, g: "acme-labs" }, BEFORE), /repository/);
  assert.match(refusal({ ...SCAN, g: "SamarthPuthraya/support-bot" }, BEFORE), /demo repository/);
  assert.match(refusal(SCAN, { nowSeconds: SCAN.x }), /over/);
  assert.match(refusal(SCAN, { nowSeconds: SCAN.x - 299 }), /under 5 of the scan's 30 minutes/);
  assert.equal(refusal(SCAN, { nowSeconds: SCAN.x - 300 }), null);
});

test("knows a GitHub repository name, and nothing a shell or a path could misread", () => {
  for (const ok of ["acme-labs/help-desk", "Microsoft/TypeScript", "a/b.c_d-e", "a1/x"]) assert.ok(isScanRepo(ok), ok);
  for (const bad of [
    "",
    "acme",
    "acme/x/y",
    "-acme/x",
    "acme/.",
    "acme/..",
    "acme/x y",
    "acme/$(id)",
    "acme/x;id",
    "acme/x`id`",
    "../x",
    `${"a".repeat(40)}/x`,
    `a/${"b".repeat(101)}`,
    "acme/x\nrepo=evil/y",
    5,
  ])
    assert.ok(!isScanRepo(bad), JSON.stringify(bad));
});

test("the ticket job writes the repository, and never the address, the key or the ticket", () => {
  const fields = { ...SCAN, x: Math.floor(Date.now() / 1000) + 1800 };
  const sealed = seal(SECRET, fields);
  const run = runStep("repo", { inputs: { ticket: sealed } });
  assert.equal(run.status, 0, run.stdout);
  assert.equal(run.output, "repo=acme-labs/help-desk\n");
  assert.equal(run.stdout.trim(), "Repository scan for one Jira site: github.com/acme-labs/help-desk.");
  assert.ok(!run.stdout.includes(fields.u));
  assert.ok(!run.stdout.includes(sealed));
});

test("the send job masks the address and key before writing them", () => {
  const fields = { ...SCAN, x: Math.floor(Date.now() / 1000) + 1800 };
  const key = signingKey(SECRET, fields.r);
  const run = runStep("send", { inputs: { ticket: seal(SECRET, fields) } });
  assert.equal(run.status, 0, run.stdout);
  assert.equal(run.output, `url=${fields.u}\nkey=${key}\nrepo=acme-labs/help-desk\n`);
  assert.deepEqual(run.stdout.trim().split("\n"), [
    `::add-mask::${fields.u}`,
    `::add-mask::${key}`,
    "Ticket checked again for the send.",
  ]);
});

test("refuses a live check's ticket, a late one and a bad mode, and writes nothing", () => {
  const now = Math.floor(Date.now() / 1000);
  const check = seal(SECRET, { u: SCAN.u, r: SCAN.r, b: "main", m: "claude-sonnet-5-5", x: now + 1800 });
  const asCheck = runStep("repo", { inputs: { ticket: check } });
  assert.equal(asCheck.status, 1);
  assert.match(asCheck.stdout, /::error::Not running: the ticket isn't a repository scan's/);
  assert.equal(asCheck.output, "");

  const late = runStep("send", { inputs: { ticket: seal(SECRET, { ...SCAN, x: now + 120 }) } });
  assert.equal(late.status, 1);
  assert.match(late.stdout, /under 5 of the scan's 30 minutes/);
  assert.equal(late.output, "");

  const bad = runStep("print", { inputs: { ticket: seal(SECRET, { ...SCAN, x: now + 1800 }) } });
  assert.equal(bad.status, 2);
  assert.equal(bad.output, "");
});
