/*
 * Places tab: "Recent arrivals and departures" panel (P19/WP9).
 *
 * Purpose    : Surface the geofence-crossing history GET /api/places/events
 *              and GET /api/groups/events already record but nothing in the
 *              dashboard showed (gap-audit P19: only the CLI and MCP read
 *              them; GET /api/groups/events had no consumer at all).
 * Inputs     : GET /api/places/events?limit=N (one row per device crossing a
 *              place) and GET /api/groups/events?limit=N (one row per
 *              quorum-gated group crossing, already carrying an honest
 *              `note` — see findplus.groups.quorum.group_event_note); GET
 *              /api/config for the one alerts-latency honesty sentence,
 *              which applies here verbatim (arrivals and departures are
 *              exactly what that sentence is about, not only alert delivery).
 * Outputs    : List rows inside #fp-places-events-list, the empty state, and
 *              the "Show more" button places.html already has.
 * Constraints: Every element is built with createElement/textContent, never
 *              raw markup. No lock/purge-worthy state survives here: the
 *              list is rebuilt from a fresh fetch every refresh() and holds
 *              nothing between calls except how many rows are requested.
 */
"use strict";

import { api } from "./api.js";
import { state } from "./state.js";
import { t } from "./i18n.js";
import { labelMap, visibleDevices } from "./device_label.js";
import { absoluteTime, relativeTime } from "./rel_time.js";
import { paneError } from "./pane_error.js";
import { markForLinks } from "./person_links.js";

const PAGE_SIZE = 20;
const POLL_MS = 45000; // matches main.js's own status-refresh cadence

let listEl = null;
let emptyEl = null;
let moreBtn = null;
let noticeEl = null;
let shown = PAGE_SIZE;
let pollTimer = null;

export function init(container) {
  if (!container) return;
  listEl = document.getElementById("fp-places-events-list");
  emptyEl = document.getElementById("fp-places-events-empty");
  moreBtn = document.getElementById("fp-places-events-more");
  noticeEl = document.getElementById("fp-places-events-notice");
  if (moreBtn) moreBtn.addEventListener("click", onShowMore);

  // UAT2 N12's pattern (places.js/groups.js/alerts.js's own init()): a locked
  // cold boot must not fire an authenticated fetch at all, not merely catch
  // its 401 -- the browser logs "Failed to load resource: 401" to the
  // console regardless of what the JS does with the response. places.js's
  // refreshAll() (run from lock.js's refreshTabsAfterUnlock()) reaches
  // refresh() again once unlocked, with no reload needed.
  if (!state.locked) {
    loadNotice();
    refresh();
  }

  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    if (!state.locked) refresh();
  }, POLL_MS);
}

/** honesty.ALERTS_LATENCY, read straight off /api/config rather than
 * duplicated here — this panel's own fetch rather than a new entry in
 * notices.js (that module is mid-edit elsewhere this round; every value it
 * injects already comes from this same /api/config response, so a second,
 * independent read of it is no less canonical). */
async function loadNotice() {
  if (!noticeEl) return;
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const cfg = await res.json();
    const notice = cfg.notices && cfg.notices.alerts_latency;
    if (notice) noticeEl.textContent = notice;
  } catch (_) {
    // Not fatal: the panel still works without the caption.
  }
}

function deviceEventText(row, labels) {
  const verb = row.event_type === "ENTER" ? t("places.events.entered") : t("places.events.left");
  return t("places.events.deviceLine", {
    // The shared label helper, so two trackers with one name read apart.
    device: labels.get(row.device_id) || row.device_name || row.device_id,
    verb,
    place: row.place_name,
  });
}

/** Group rows already carry an honest, server-composed `note` (which member
 * count crossed, out of how many, and a stale-member caveat) -- it just
 * never names the group itself, since one note can serve every consumer. */
function groupEventText(row) {
  return t("places.events.groupLine", { group: row.group_name, note: row.note });
}

async function fetchEvents(limit) {
  const [placeRows, groupRows] = await Promise.all([
    api(`/api/places/events?limit=${limit}`),
    api(`/api/groups/events?limit=${limit}`),
  ]);
  const labels = labelMap(visibleDevices());
  const merged = [
    ...placeRows.map((r) => ({ time: r.observed_at, text: deviceEventText(r, labels), kind: r.event_type })),
    ...groupRows.map((r) => ({ time: r.observed_at, text: groupEventText(r), kind: r.event_type })),
  ];
  merged.sort((a, b) => new Date(b.time) - new Date(a.time));
  return merged.slice(0, limit);
}

function renderRow(entry) {
  const li = document.createElement("li");
  li.className = "fp-events-row";
  if (entry.kind) li.dataset.kind = String(entry.kind).toLowerCase();
  const text = document.createElement("span");
  text.className = "fp-events-text";
  text.textContent = entry.text;
  markForLinks(text);
  // Relative first ("12 minutes ago"); the exact time is the hover title and
  // the machine-readable datetime, so nothing is lost.
  const time = document.createElement("time");
  time.className = "fp-events-time";
  time.dateTime = entry.time;
  time.title = absoluteTime(entry.time);
  time.textContent = relativeTime(entry.time);
  li.append(text, time);
  return li;
}

/** A failed load says so, with Retry, instead of leaving the old rows or nothing. */
function showError(err) {
  if (!listEl) return;
  if (emptyEl) emptyEl.hidden = true;
  if (moreBtn) moreBtn.hidden = true;
  listEl.replaceChildren(
    paneError({ title: t("places.events.loadFailed"), message: err.message, onRetry: refresh }),
  );
}

export async function refresh() {
  if (!listEl) return;
  let rows;
  try {
    rows = await fetchEvents(shown);
  } catch (err) {
    // Locked: api() already showed the lock screen, say nothing here.
    if (err.message !== "Locked") showError(err);
    return;
  }
  while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
  if (rows.length === 0) {
    if (emptyEl) emptyEl.hidden = false;
    if (moreBtn) moreBtn.hidden = true;
    return;
  }
  if (emptyEl) emptyEl.hidden = true;
  rows.forEach((r) => listEl.appendChild(renderRow(r)));
  // A full page back could mean there is more; fewer rows than asked for
  // means this was everything there is.
  if (moreBtn) moreBtn.hidden = rows.length < shown;
}

function onShowMore() {
  shown += PAGE_SIZE;
  refresh();
}

/** places.js's purge() hook: real device/group names and timestamps must not
 * survive behind the lock screen (PROMPT.md §2 invariant 11), and the poll
 * timer must not keep fetching while locked. */
export function purge() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  shown = PAGE_SIZE;
  if (listEl) while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
  if (emptyEl) emptyEl.hidden = true;
  if (moreBtn) moreBtn.hidden = true;
}
