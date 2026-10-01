/*
 * The Devices dialog's search, sort and last-seen text.
 *
 * Purpose    : With 17 trackers the dialog was a long unsearchable list. This
 *              adds a search box, a sort choice, a "showing N of M" count and
 *              per-row "last seen" and battery text, and makes the Track all /
 *              Track none buttons act on the rows that are showing.
 * Inputs     : state.status.devices[].latest_observation (age, battery) and
 *              the rendered #device-list rows (devices.js builds them).
 * Outputs    : A toolbar before #device-list; row order and `hidden` flags.
 * Constraints: Sorting moves the existing row nodes, so ticks the user has not
 *              saved yet survive. Text is set with textContent only. A row's
 *              "last seen" is the time of its newest location, never a claim
 *              that the tracker is still there.
 */
"use strict";

import { $, state, fmtDuration } from "./state.js";
import { t } from "./i18n.js";

/** A last sighting older than this is flagged as stale. */
const STALE_SECONDS = 24 * 3600;

const rows = () => [...document.querySelectorAll("#device-list .device-row")];

/** The newest sighting the status feed holds for a device, or null. */
function latestFor(deviceId) {
  const entry = ((state.status && state.status.devices) || []).find((d) => d.device_id === deviceId);
  return entry && entry.latest_observation;
}

/** Add "Last seen 4 min ago" and battery text to a row's meta line. */
export function decorateRow(row, device) {
  const latest = latestFor(device.device_id);
  const meta = row.querySelector(".d-meta");
  const seen = document.createElement("span");
  seen.className = "d-seen";
  if (latest) {
    seen.textContent = t("devices.lastSeen", { age: fmtDuration(latest.age_seconds) });
    if (latest.age_seconds > STALE_SECONDS) seen.classList.add("is-stale");
    row.dataset.age = String(latest.age_seconds);
  } else {
    seen.textContent = t("devices.neverSeen");
    row.dataset.age = "Infinity";
  }
  meta.appendChild(seen);
  if (latest && latest.battery_level) {
    const battery = document.createElement("span");
    battery.className = "d-battery";
    battery.textContent = t("devices.batteryAt", { n: latest.battery_level });
    meta.appendChild(battery);
  }
  row.dataset.search = [device.name, device.label, device.device_id, device.provider].join(" ").toLowerCase();
  row.dataset.name = (device.label || device.name || "").toLowerCase();
  row.classList.toggle("is-untracked", !device.is_tracked);
}

const SORTS = {
  tracked: (a, b) => (b.querySelector("input").checked - a.querySelector("input").checked) || byName(a, b),
  name: (a, b) => byName(a, b),
  seen: (a, b) => (Number(a.dataset.age) - Number(b.dataset.age) || 0) || byName(a, b),
};

function byName(a, b) {
  return a.dataset.name.localeCompare(b.dataset.name) || a.dataset.deviceId.localeCompare(b.dataset.deviceId);
}

/** Filter by the search text, order by the sort choice, update the count. */
export function applyView() {
  const bar = $("device-tools");
  if (!bar) return;
  const needle = bar.querySelector("input").value.trim().toLowerCase();
  const sort = SORTS[bar.querySelector("select").value] || SORTS.tracked;
  const host = $("device-list");
  const all = rows();
  all.sort(sort).forEach((row) => host.appendChild(row));
  let shown = 0;
  all.forEach((row) => {
    row.hidden = Boolean(needle) && !row.dataset.search.includes(needle);
    if (!row.hidden) shown += 1;
  });
  const none = host.querySelector(".device-none");
  if (none) none.remove();
  if (all.length && !shown) {
    const note = document.createElement("div");
    note.className = "empty device-none";
    note.textContent = t("devices.noMatch", { query: needle });
    host.appendChild(note);
  }
  bar.querySelector(".device-count").textContent = all.length > 1 ? t("devices.showingCount", { shown, total: all.length }) : "";
}

/** Build the toolbar once, above the list. */
export function mountToolbar() {
  if ($("device-tools") || !rows().length) return;
  const bar = document.createElement("div");
  bar.id = "device-tools";
  bar.className = "device-tools";
  const search = document.createElement("input");
  search.type = "search";
  search.setAttribute("aria-label", t("devices.searchLabel"));
  search.placeholder = t("devices.searchPlaceholder");
  const sort = document.createElement("select");
  sort.setAttribute("aria-label", t("devices.sortLabel"));
  for (const key of ["tracked", "name", "seen"]) {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = t(`devices.sort.${key}`);
    sort.appendChild(opt);
  }
  const count = document.createElement("span");
  count.className = "device-count";
  count.setAttribute("aria-live", "polite");
  bar.append(search, sort, count);
  search.addEventListener("input", applyView);
  sort.addEventListener("change", applyView);
  $("device-list").before(bar);
}

/** Dialog opened again: start from a clean search, keep the sort. */
export function resetSearch() {
  const bar = $("device-tools");
  if (bar) bar.querySelector("input").value = "";
}

/** Track all / none touch only the rows the search leaves showing. */
export function setVisibleChecked(value) {
  rows().filter((r) => !r.hidden).forEach((r) => { r.querySelector("input").checked = value; });
}

