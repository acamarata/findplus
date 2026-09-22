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
 * "sent"/"skipped" render as-is. A "retrying" row reports the attempt that is
 * coming next (attempts + 1) and when; a "failed" row that used up every
 * retry says so, distinct from a "failed" row that never qualified for one
 * (attempts stays 1 for those, per notifications.md's retry ruling).
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
  return delivery.status;
}

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text;
  // Text/Body/Error truncate with an ellipsis at 1280 (components.css,
  // R-P2-28 point 6); the title carries the full value for anyone who wants
  // it without needing to widen the pane.
  if (text) td.title = text;
  return td;
}

function buildDeliveryRow(delivery) {
  const tr = document.createElement("tr");
  tr.append(
    cell(delivery.rule_name || t("alerts.ruleFallback", { id: delivery.rule_id })),
    cell(delivery.channel || t("common.emptyValue")),
    cell(delivery.event_kind),
    // notifications.md §2: `text` (subject + verb) and `body` (place and the
    // observed/lag line) are rendered server-side per row, so an edited place
    // or device name is reflected on the next read. They are only computed for
    // native rows; every other channel sends the em dash placeholder.
    cell(delivery.text || t("common.emptyValue")),
    cell(delivery.body || t("common.emptyValue")),
    cell(fmtDateTime(delivery.sent_at)),
    cell(statusText(delivery)),
    // A "skipped" row arrived with an empty Error cell and no hint why; the
    // API now sends the reason in `error`, and a bare skip still says so.
    cell(delivery.error || (delivery.status === "skipped" ? t("alerts.skippedNoReason") : "")),
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
