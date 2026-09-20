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
import { $, fmtDateTime } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text;
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
    cell(delivery.status),
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
