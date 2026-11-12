// Opens the ticket Modelpin for Jira sealed when a Jira admin started a live check, and gives this run what it
// needs to report back to that one Jira site:
//   - the site's web trigger address, as this step's output "url";
//   - the signing key for that one request, as this step's output "key";
//   - the replacement model to check, as LIVE_MODEL in $GITHUB_ENV.
// The ticket is read from the run's event payload ($GITHUB_EVENT_PATH), never from a step's env, so the run log
// doesn't show it. The address and key are masked before they are written, and only the two steps that send
// results to Jira are given them; nothing prints them.
//
// The format is Modelpin for Jira's (apps/jira/src/domain/live.ts in modelpin-atlassian):
//   ticket = "v1." + base64url(iv | ciphertext | tag), AES-256-GCM, additional data "modelpin-live-v1",
//            key = HMAC-SHA256(secret, "modelpin-live-seal-v1")
//   signing key = hex HMAC-SHA256(secret, "modelpin-live-sign-v1|" + request id)
// No dependencies: Node's own crypto, as on every GitHub-hosted runner.

import { createDecipheriv, createHmac } from "node:crypto";
import { appendFileSync, readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export const REPLACEMENTS = ["claude-sonnet-5-5", "claude-sonnet-5", "claude-sonnet-4-6"];
export const BRANCHES = ["main", "fixed-prompt"];
// A check takes about 2 minutes, and Jira takes no results once the ticket's 30 minutes are over.
export const MIN_SECONDS_LEFT = 5 * 60;

const REQUEST_ID = /^[0-9a-f]{32}$/;
const WEB_TRIGGER = /^https:\/\/[a-z0-9-]+\.webtrigger\.atlassian\.app\/public\/[A-Za-z0-9_-]+$/;

function hmac(secret, text) {
  return createHmac("sha256", Buffer.from(secret, "utf8")).update(text, "utf8");
}

export function signingKey(secret, requestId) {
  return hmac(secret, `modelpin-live-sign-v1|${requestId}`).digest("hex");
}

/** The ticket's fields, or null when it wasn't sealed with this secret or was changed. */
export function openTicket(secret, sealed) {
  if (typeof sealed !== "string" || !sealed.startsWith("v1.")) return null;
  const raw = Buffer.from(sealed.slice(3), "base64url");
  if (raw.length < 12 + 16 + 2) return null;
  try {
    const decipher = createDecipheriv(
      "aes-256-gcm",
      hmac(secret, "modelpin-live-seal-v1").digest(),
      raw.subarray(0, 12),
    );
    decipher.setAAD(Buffer.from("modelpin-live-v1", "utf8"));
    decipher.setAuthTag(raw.subarray(raw.length - 16));
    const plain = Buffer.concat([
      decipher.update(raw.subarray(12, raw.length - 16)),
      decipher.final(),
    ]).toString("utf8");
    return JSON.parse(plain);
  } catch {
    return null;
  }
}

/** The sealed ticket in the run's event payload: the workflow_dispatch input "ticket", or "" when there is none. */
export function sealedFromEvent(event) {
  const ticket = event && typeof event === "object" ? event.inputs?.ticket : undefined;
  return typeof ticket === "string" ? ticket : "";
}

/** Why this run won't use the ticket, or null when it may. */
export function refusal(ticket, { branch, nowSeconds }) {
  if (!ticket || typeof ticket !== "object") return "the ticket wasn't sealed by Modelpin for Jira with this repository's secret";
  if (typeof ticket.u !== "string" || !WEB_TRIGGER.test(ticket.u)) return "the ticket's address isn't a Forge web trigger";
  if (typeof ticket.r !== "string" || !REQUEST_ID.test(ticket.r)) return "the ticket names no request";
  if (!REPLACEMENTS.includes(ticket.m)) return "the ticket names a model this demo doesn't check";
  if (!BRANCHES.includes(ticket.b) || ticket.b !== branch) return `the ticket is for the ${ticket.b} branch, and this run is on ${branch}`;
  if (typeof ticket.x !== "number" || ticket.x <= nowSeconds) return "the live check's 30 minutes are over; start a new one in Jira";
  if (ticket.x - nowSeconds < MIN_SECONDS_LEFT) {
    return "under 5 of the live check's 30 minutes are left, too few to finish before Jira stops taking results; start a new one in Jira";
  }
  return null;
}

function readEvent(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

function main() {
  const sealed = sealedFromEvent(readEvent(process.env.GITHUB_EVENT_PATH ?? ""));
  const ticket = openTicket(process.env.MODELPIN_LIVE_SECRET ?? "", sealed);
  const why = refusal(ticket, {
    branch: process.env.GITHUB_REF_NAME ?? "",
    nowSeconds: Math.floor(Date.now() / 1000),
  });
  if (why) {
    console.log(`::error::Not running: ${why}.`);
    process.exit(1);
  }
  const key = signingKey(process.env.MODELPIN_LIVE_SECRET, ticket.r);
  // Masked first, so no later step can print them. Step outputs, not $GITHUB_ENV, so only the steps that send
  // results to Jira get them.
  console.log(`::add-mask::${ticket.u}`);
  console.log(`::add-mask::${key}`);
  appendFileSync(process.env.GITHUB_OUTPUT, `url=${ticket.u}\nkey=${key}\n`);
  appendFileSync(process.env.GITHUB_ENV, `LIVE_MODEL=${ticket.m}\n`);
  console.log(`Live check for one Jira site: ${ticket.b} branch, claude-sonnet-4-5-20250929 against ${ticket.m}.`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
