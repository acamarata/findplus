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
 *              no top-level side effects of its own. `sent_at` renders as the
 *              raw ISO string: neither state.js nor alerts_rules.js exports a
 *              relative-time helper, and this ticket does not add one.
 */
"use strict";
import { $ } from "./state.js";
import { api } from "./api.js";

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text;
  return td;
}

function buildDeliveryRow(delivery) {
  const tr = document.createElement("tr");
  tr.append(
    cell(delivery.rule_name || `rule ${delivery.rule_id}`),
    cell(delivery.channel || "—"),
    cell(delivery.event_kind),
    cell(delivery.sent_at || ""),
    cell(delivery.status),
    cell(delivery.error || ""),
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
