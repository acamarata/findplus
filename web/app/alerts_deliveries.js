/*
 * Alerts tab: the delivery log table. Split out of alerts.js at the PRI
 * rule-7 300-line file cap, matching the alerts_rules.js split.
 *
 * Purpose    : Show what actually happened to each alert — which rule fired,
 *              over which channel, whether it was sent, failed or skipped, and
 *              the error text when there is one. The rows were written to
 *              alert_deliveries since 1.0 and never surfaced (CF-14).
 * Inputs     : GET /api/alerts/deliveries.
 * Outputs    : Rows inside #fp-deliveries-tbody.
 * Constraints: textContent only, never raw markup. alerts.js owns the wiring
 *              and re-exports purge()/refreshAll() for lock.js; this module has
 *              no top-level side effects of its own. Every timestamp in this
 *              table (Sent, and Retrying's "next at") renders through this
 *              file's own fmtDeliveryTime() rather than state.js's
 *              fmtDateTime/fmtTime: UAT6 N17 found the two mixed inside this
 *              one table (a full date+time in Sent, a bare time-of-day in
 *              "next at") and asked for one formatter here; it also appends
 *              the zone abbreviation, matching timeline.js's "Observed …
 *              EDT" elsewhere in the dashboard (state.js's own formatters,
 *              used everywhere else, carry no zone -- that is state.js's
 *              scope, not this file's, and out of this ticket's file list).
 */
"use strict";
import { $ } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";

/** One formatter for every timestamp this table shows -- see the module
 *  docstring above. Returns null for a missing timestamp so each caller
 *  decides its own "nothing to show" wording instead of a bare "—". */
function fmtDeliveryTime(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  const datePart = d.toLocaleString([], {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
  const zone = d.toLocaleTimeString([], { timeZoneName: "short" }).split(" ").pop();
  return `${datePart} ${zone}`;
}

// Mirrors findplus.alerts.dispatch_core.MAX_ATTEMPTS (1 initial send + 3
// retries): the server enforces the real cap, this only picks the wording.
const MAX_DELIVERY_ATTEMPTS = 4;

/**
 * "sent"/"skipped"/… go through the alerts.statuses.* catalog (UAT U22). A
 * "retrying" row reports the attempt that is coming next (attempts + 1) and,
 * when the server has actually scheduled one, when; a "failed" row that used
 * up every retry says so, distinct from a "failed" row that never qualified
 * for one (attempts stays 1 for those, per notifications.md's retry ruling).
 *
 * UAT6 N17: a null `next_attempt_at` used to still render "next at —"
 * (fmtTime()'s own placeholder for a missing value) inside the sentence,
 * which reads as a promise the server never made -- the clause is dropped
 * instead of filled with a dash.
 */
function statusText(delivery) {
  const attempts = delivery.attempts || 1;
  if (delivery.status === "retrying") {
    const nextAt = fmtDeliveryTime(delivery.next_attempt_at);
    return nextAt
      ? t("alerts.retryingStatus", { attempt: attempts + 1, max: MAX_DELIVERY_ATTEMPTS, time: nextAt })
      : t("alerts.retryingStatusNoTime", { attempt: attempts + 1, max: MAX_DELIVERY_ATTEMPTS });
  }
  if (delivery.status === "failed" && attempts >= MAX_DELIVERY_ATTEMPTS) {
    return t("alerts.failedAfterRetries", { max: MAX_DELIVERY_ATTEMPTS });
  }
  return t("alerts.statuses." + delivery.status);
}

/**
 * "Sent" reads as "this went out" -- gated on whether the row actually
 * carries a `sent_at`, not on its current `status` (UAT6 N17: a row can be
 * sent successfully and later marked failed for a downstream reason, and the
 * old status-based gate showed "—" for it even though it really was sent at
 * that time; a "queued" row with no `sent_at` yet still shows nothing, same
 * as before).
 */
function sentText(delivery) {
  return fmtDeliveryTime(delivery.sent_at) || t("common.emptyValue");
}

/** A labelled `<td>` for the phone-tier card layout (responsive.css turns
 *  data-label into the row's own heading below 600px, UAT U9). */
function cell(text, label) {
  const td = document.createElement("td");
  td.textContent = text;
  td.dataset.label = label;
  // Title carries the full value for anyone who wants it without widening
  // the pane; below 600px the card layout wraps instead of truncating.
  if (text) td.title = text;
  return td;
}

/** Text/Body (notifications.md §2's rendered message) render for every
 *  channel now (UAT3 N18: the server used to render it only when the
 *  request itself was filtered to `?channel=native`, so the unfiltered
 *  delivery log the dashboard actually loads showed the dash on every row,
 *  including its own Desktop notifications; UAT4 N32: the server then
 *  widened rendering to every channel, not native only -- a telegram/
 *  whatsapp/webhook row's source event resolves through the exact same
 *  batched renderer, so there is no longer a channel-shaped reason for one
 *  row to show real text and another to show a placeholder note). A `null`
 *  text now means one thing for every channel: the source event was purged
 *  by retention before this row was ever shown, so the dash the app uses
 *  everywhere for "we don't know" is the honest answer here too. Long
 *  values collapse behind a native `<details>` once they are long enough to
 *  squeeze the 360px pane (U9); a short value renders plainly. */
function detailsCell(text, label, threshold = 30) {
  const value = text || t("common.emptyValue");
  if (!text || text.length <= threshold) return cell(value, label);
  const td = document.createElement("td");
  td.dataset.label = label;
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = value.slice(0, threshold) + "…";
  const body = document.createElement("p");
  body.textContent = value;
  details.append(summary, body);
  td.appendChild(details);
  return td;
}

/**
 * UAT6 N17: the Error column used to show whatever the channel's own client
 * library raised verbatim -- "HTTPSConnectionPool(host='api.telegram.org'…
 * NameResolutionError)" -- a Python exception repr, not something a user can
 * act on, and long enough to overflow the 375px pane on its own (no spaces
 * for the browser to wrap on). Each pattern below is a shape the channel
 * clients (requests/httpx under Telegram/webhook/WhatsApp) are actually
 * known to raise; anything unrecognised still gets a short, honest fallback
 * instead of the raw text. The raw text is never gone -- it sits in the
 * cell's `title` (cell()'s own convention) for anyone who needs it.
 */
const ERROR_PATTERNS = [
  [/NameResolution|getaddrinfo|Name or service not known|ConnectionError|HTTPSConnectionPool|HTTPConnectionPool|Connection refused|Network is unreachable/i, "alerts.deliveries.errorNetwork"],
  [/timed? ?out|TimeoutError|ReadTimeout|ConnectTimeout/i, "alerts.deliveries.errorTimeout"],
  [/\b401\b|\b403\b|Unauthorized|Forbidden|invalid token|bot was blocked/i, "alerts.deliveries.errorAuth"],
];

/** The short catalog sentence for a raw error string, or the generic
 *  fallback when nothing above recognises its shape. */
function friendlyErrorText(raw, channel) {
  const channelName = channel ? t("alerts.channels." + channel) : t("common.emptyValue");
  const match = ERROR_PATTERNS.find(([pattern]) => pattern.test(raw));
  return t(match ? match[1] : "alerts.deliveries.errorGeneric", { channel: channelName });
}

/** The Error column: a short, mapped sentence as the visible text, the raw
 *  detail (an exception repr, or the skipped-reason sentence) as the title
 *  for anyone who wants it -- see friendlyErrorText() above. */
function errorCell(delivery) {
  const label = t("alerts.colError");
  const raw = delivery.error || (delivery.status === "skipped" ? t("alerts.skippedNoReason") : "");
  const td = document.createElement("td");
  td.dataset.label = label;
  if (raw) {
    td.textContent = delivery.error ? friendlyErrorText(raw, delivery.channel) : raw;
    td.title = raw;
  }
  return td;
}

function buildDeliveryRow(delivery) {
  const tr = document.createElement("tr");
  tr.append(
    cell(delivery.rule_name || t("alerts.ruleFallback", { id: delivery.rule_id }), t("alerts.colRule")),
    cell(delivery.channel ? t("alerts.channels." + delivery.channel) : t("common.emptyValue"), t("alerts.colChannel")),
    // '' for every channel with no per-target concept; a telegram row's own
    // target (chat id/username) otherwise -- the per-target outcome the
    // owner asked "send test" and the delivery log both surface.
    cell(delivery.target || t("common.emptyValue"), t("alerts.colDeliveryTarget")),
    cell(delivery.event_kind ? t("alerts.kinds." + delivery.event_kind) : t("common.emptyValue"), t("alerts.colKind")),
    detailsCell(delivery.text, t("alerts.deliveries.text")),
    detailsCell(delivery.body, t("alerts.deliveries.body")),
    cell(sentText(delivery), t("alerts.colSent")),
    cell(statusText(delivery), t("alerts.colStatus")),
    // A "skipped" row arrived with an empty Error cell and no hint why; the
    // API now sends the reason in `error`, and a bare skip still says so
    // (errorCell() maps a real exception to a short sentence; UAT6 N17).
    errorCell(delivery),
  );
  return tr;
}

export function renderDeliveriesTable(deliveries) {
  const tbody = $("fp-deliveries-tbody");
  if (!tbody) return;
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
  deliveries.forEach((delivery) => tbody.appendChild(buildDeliveryRow(delivery)));
}

export async function loadDeliveries() {
  renderDeliveriesTable(await api("/api/alerts/deliveries"));
}

/** lock.js purgeRenderedData() hook: rule and place names must not survive the lock. */
export function purgeDeliveries() {
  renderDeliveriesTable([]);
}
