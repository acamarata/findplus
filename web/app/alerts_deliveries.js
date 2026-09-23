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
 *              no top-level side effects of its own. `sent_at` renders in the
 *              viewer's local time via state.fmtDateTime, like every other
 *              timestamp in this dashboard: a raw "...+00:00" in a log of when
 *              alerts went out is read as local and misinforms by hours
 *              (honesty round 2 F14).
 */
"use strict";
import { $, fmtDateTime, fmtTime } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";

// Mirrors findplus.alerts.dispatch_core.MAX_ATTEMPTS (1 initial send + 3
// retries): the server enforces the real cap, this only picks the wording.
const MAX_DELIVERY_ATTEMPTS = 4;

/**
 * "sent"/"skipped"/… go through the alerts.statuses.* catalog (UAT U22). A
 * "retrying" row reports the attempt that is coming next (attempts + 1) and
 * when; a "failed" row that used up every retry says so, distinct from a
 * "failed" row that never qualified for one (attempts stays 1 for those, per
 * notifications.md's retry ruling).
 */
function statusText(delivery) {
  const attempts = delivery.attempts || 1;
  if (delivery.status === "retrying") {
    return t("alerts.retryingStatus", {
      attempt: attempts + 1,
      max: MAX_DELIVERY_ATTEMPTS,
      time: fmtTime(delivery.next_attempt_at),
    });
  }
  if (delivery.status === "failed" && attempts >= MAX_DELIVERY_ATTEMPTS) {
    return t("alerts.failedAfterRetries", { max: MAX_DELIVERY_ATTEMPTS });
  }
  return t("alerts.statuses." + delivery.status);
}

/** "Sent" reads as "this went out" -- a "failed" or still-"queued" row never
 *  did, so the timestamp (really "first attempted at", alerts/retry.py) stays
 *  out of that column for those two statuses rather than implying it (U22). */
function sentText(delivery) {
  if (delivery.status === "failed" || delivery.status === "queued") return t("common.emptyValue");
  return fmtDateTime(delivery.sent_at);
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
 *  native row now (UAT3 N18: the server used to render it only when the
 *  request itself was filtered to `?channel=native`, so the unfiltered
 *  delivery log the dashboard actually loads showed the dash on every row,
 *  including its own Desktop notifications). Every other channel builds its
 *  message inline when it sends (the webhook JSON payload, the Telegram/
 *  WhatsApp text) instead of storing a second copy here, so those rows say
 *  that plainly rather than showing the same dash the app uses for "we
 *  don't know" -- a purged native event (source event pruned by retention)
 *  is the one case where the dash is the honest answer, so that one keeps
 *  it. Long values collapse behind a native `<details>` once they are long
 *  enough to squeeze the 360px pane (U9); a short value renders plainly. */
function detailsCell(text, label, channel, threshold = 30) {
  if (!text && channel && channel !== "native") {
    const value = t("alerts.deliveries.notNativeText", { channel: t("alerts.channels." + channel) });
    return cell(value, label);
  }
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

function buildDeliveryRow(delivery) {
  const tr = document.createElement("tr");
  tr.append(
    cell(delivery.rule_name || t("alerts.ruleFallback", { id: delivery.rule_id }), t("alerts.colRule")),
    cell(delivery.channel ? t("alerts.channels." + delivery.channel) : t("common.emptyValue"), t("alerts.colChannel")),
    cell(delivery.event_kind ? t("alerts.kinds." + delivery.event_kind) : t("common.emptyValue"), t("alerts.colKind")),
    detailsCell(delivery.text, t("alerts.deliveries.text"), delivery.channel),
    detailsCell(delivery.body, t("alerts.deliveries.body"), delivery.channel),
    cell(sentText(delivery), t("alerts.colSent")),
    cell(statusText(delivery), t("alerts.colStatus")),
    // A "skipped" row arrived with an empty Error cell and no hint why; the
    // API now sends the reason in `error`, and a bare skip still says so.
    cell(delivery.error || (delivery.status === "skipped" ? t("alerts.skippedNoReason") : ""), t("alerts.colError")),
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
