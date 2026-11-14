// Opens the ticket Modelpin for Jira sealed when a Jira admin started a repository scan, for the workflow "Modelpin
// repository scan" (.github/workflows/modelpin-scan.yml). Two uses, one per job:
//   node open-scan.mjs repo   the "ticket" job: checks the ticket and writes the repository to scan ("owner/name")
//                             as this step's output "repo". The name is public, so it isn't masked.
//   node open-scan.mjs send   the "send" job: checks the ticket again and writes the site's web trigger address and
//                             the request's signing key, masked first, as this step's outputs "url" and "key".
// The scan job in between gets neither secret nor ticket. The ticket is read from the run's event payload, never
// from a step's env, so the run log doesn't show it.
//
// The format is Modelpin for Jira's (apps/jira/src/domain/live.ts in modelpin-atlassian): the same sealing as a live
// check's ticket (open-ticket.mjs), with { u, r, k: "scan", g, x } inside and never a branch or a model.

import { appendFileSync, readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { MIN_SECONDS_LEFT, openTicket, sealedFromEvent, signingKey } from "./open-ticket.mjs";

const REQUEST_ID = /^[0-9a-f]{32}$/;
const WEB_TRIGGER = /^https:\/\/[a-z0-9-]+\.webtrigger\.atlassian\.app\/public\/[A-Za-z0-9_-]+$/;
// GitHub's rules, as Modelpin for Jira and the start page check them.
const REPO = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}$/;
const DEMO = "samarthputhraya/support-bot";

export function isScanRepo(value) {
  return typeof value === "string" && REPO.test(value) && !value.endsWith("/.") && !value.endsWith("/..");
}

/** Why this run won't use the ticket, or null when it may. */
export function refusal(ticket, { nowSeconds }) {
  if (!ticket || typeof ticket !== "object") return "the ticket wasn't sealed by Modelpin for Jira with this repository's secret";
  if (ticket.k !== "scan" || "b" in ticket || "m" in ticket) return "the ticket isn't a repository scan's";
  if (typeof ticket.u !== "string" || !WEB_TRIGGER.test(ticket.u)) return "the ticket's address isn't a Forge web trigger";
  if (typeof ticket.r !== "string" || !REQUEST_ID.test(ticket.r)) return "the ticket names no request";
  if (!isScanRepo(ticket.g)) return "the ticket names no GitHub repository";
  if (ticket.g.toLowerCase() === DEMO) return "the ticket names the demo repository, which a live check checks";
  if (typeof ticket.x !== "number" || ticket.x <= nowSeconds) return "the scan's 30 minutes are over; start a new one in Jira";
  if (ticket.x - nowSeconds < MIN_SECONDS_LEFT) {
    return "under 5 of the scan's 30 minutes are left, too few to finish before Jira stops taking results; start a new one in Jira";
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

function main(mode) {
  if (mode !== "repo" && mode !== "send") {
    console.log("::error::Usage: node open-scan.mjs repo|send");
    process.exit(2);
  }
  const secret = process.env.MODELPIN_LIVE_SECRET ?? "";
  const ticket = openTicket(secret, sealedFromEvent(readEvent(process.env.GITHUB_EVENT_PATH ?? "")));
  const why = refusal(ticket, { nowSeconds: Math.floor(Date.now() / 1000) });
  if (why) {
    console.log(`::error::Not running: ${why}.`);
    process.exit(1);
  }
  if (mode === "repo") {
    appendFileSync(process.env.GITHUB_OUTPUT, `repo=${ticket.g}\n`);
    console.log(`Repository scan for one Jira site: github.com/${ticket.g}.`);
    return;
  }
  const key = signingKey(secret, ticket.r);
  // Masked first, so no later step can print them. Step outputs, so only the step that sends the scan gets them.
  console.log(`::add-mask::${ticket.u}`);
  console.log(`::add-mask::${key}`);
  appendFileSync(process.env.GITHUB_OUTPUT, `url=${ticket.u}\nkey=${key}\nrepo=${ticket.g}\n`);
  console.log("Ticket checked again for the send.");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main(process.argv[2]);
