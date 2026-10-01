/*
 * Alerts tab: the delivery log's status and channel filters, and its paging.
 *
 * Purpose    : A log of a hundred rows needs a way to find the failures. Two
 *              selects (status, channel) narrow it and a "Show more" button
 *              pages through it 15 rows at a time.
 * Inputs     : The delivery rows GET /api/alerts/deliveries returned.
 * Outputs    : buildFilters(host, onChange); applyFilters(rows) -> { rows (this
 *              page), total (matching), filtered (any filter on) }; showMore();
 *              clearFilters(); resetFilters().
 * Constraints: textContent only. State is module-local and never saved; the
 *              filters mean nothing once the log is purged on lock.
 */
"use strict";

import { t } from "./i18n.js";

const PAGE = 15;
const STATUSES = ["sent", "failed", "retrying", "skipped", "queued", "delivered"];
const CHANNELS = ["telegram", "webhook", "whatsapp", "native"];
let status = "";
let channel = "";
let shown = PAGE;
let host = null;

function select(id, label, anyLabel, values, i18nPrefix, onChange, assign) {
  const el = document.createElement("select");
  el.id = id;
  el.setAttribute("aria-label", label);
  [["", anyLabel], ...values.map((v) => [v, t(`${i18nPrefix}.${v}`)])].forEach(([value, text]) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = text;
    el.appendChild(opt);
  });
  el.addEventListener("change", () => {
    assign(el.value);
    shown = PAGE;
    onChange();
  });
  return el;
}

/** Mount the two selects in `hostEl` once. */
export function buildFilters(hostEl, onChange) {
  host = hostEl;
  if (!host || host.firstChild) return;
  host.append(
    select("fp-deliveries-status", t("alerts.filters.statusLabel"), t("alerts.filters.anyStatus"),
      STATUSES, "alerts.statuses", onChange, (v) => (status = v)),
    select("fp-deliveries-channel", t("alerts.filters.channelLabel"), t("alerts.filters.anyChannel"),
      CHANNELS, "alerts.channels", onChange, (v) => (channel = v)),
  );
}

/** Narrow `rows` and cut the visible page; reports how many matched in all. */
export function applyFilters(rows) {
  const matching = rows.filter((r) => (!status || r.status === status) && (!channel || r.channel === channel));
  if (host) host.hidden = rows.length === 0;
  return { rows: matching.slice(0, shown), total: matching.length, filtered: Boolean(status || channel) };
}

export function showMore() {
  shown += PAGE;
}

/** Back to "everything" (the Clear filters button). */
export function clearFilters() {
  status = "";
  channel = "";
  shown = PAGE;
  if (host) host.querySelectorAll("select").forEach((el) => (el.value = ""));
}

/** The lock hook: forget the filters and hide the bar. */
export function resetFilters() {
  clearFilters();
  if (host) host.hidden = true;
}
