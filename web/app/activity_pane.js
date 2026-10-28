/*
 * Activity pane (All Activity tab): one merged, newest-first feed for the day.
 *
 * Purpose    : Every sighting of every tracker the Show / Group filters allow,
 *              plus people's arrivals and departures, as single lines. A line
 *              click asks the map to focus that sighting.
 * Inputs     : state.day / state.timeline (the filter row's Day arrows drive
 *              them), GET /api/groups/events for the day, the person cache.
 * Outputs    : DOM inside #tab-activity; window event `findplus:focus-tracker`
 *              {device_id, point_id} on a line click (tracker_focus.js listens).
 * Constraints (contract, see panel_tabs.js):
 *   - mountActivity(container) is idempotent and runs each time the tab is
 *     shown; refreshActivity() runs on `findplus:data-refreshed`.
 *   - Redraws on `findplus:tracks-rendered` (day, Show, Group, movement or
 *     suspect change) with no refetch; events refetch per day and on refresh.
 *   - First 200 lines, then a Show more button. purgeActivity() empties the
 *     pane and every cache (lock.js purgeRenderedData).
 */
"use strict";

import { state } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";
import { button } from "./components/button.js";
import { paneError } from "./pane_error.js";
import { maybeRefreshPersonColours } from "./person_colours.js";
import { buildFeed, dayBounds } from "./activity_feed.js";
import { renderLine } from "./activity_line.js";

/** Lines shown first, and added by each Show more press. */
export const PAGE_SIZE = 200;

let root = null;
let events = [];
let eventsDay = null;
let eventsFailed = null;
let shown = PAGE_SIZE;
let viewKey = "";
let seq = 0;

const keyNow = () => [state.day, state.deviceFilter, state.groupFilter, state.movementOnly].join("|");

function openLine(line) {
  const detail = { device_id: line.deviceId, point_id: line.point.id };
  window.dispatchEvent(new CustomEvent("findplus:focus-tracker", { detail }));
}

function skeleton() {
  const note = document.createElement("div");
  note.className = "skeleton";
  note.setAttribute("role", "status");
  note.setAttribute("aria-label", t("common.loading"));
  for (let i = 0; i < 7; i += 1) note.appendChild(document.createElement("i"));
  return note;
}

function emptyNote(key) {
  const p = document.createElement("p");
  p.className = "empty fp-act-empty";
  p.textContent = t(key);
  return p;
}

function moreRow(total) {
  const row = document.createElement("div");
  row.className = "fp-act-more";
  const count = document.createElement("span");
  count.className = "fp-act-count";
  count.textContent = t("activity.more", { shown, total });
  row.append(
    count,
    button({
      label: t("activity.showMore"), variant: "secondary", size: "sm", id: "fp-act-more",
      onClick: () => { shown += PAGE_SIZE; render(); },
    })
  );
  return row;
}

function timelineFailed() {
  return Boolean(document.querySelector("#tracks [data-pane-error]"));
}

/** The pane body for the data held right now. */
function body() {
  if (!state.timeline) {
    if (!timelineFailed()) return [skeleton()];
    const err = paneError({
      title: t("activity.loadFailedTitle"), message: "", onRetry: () => import("./timeline.js").then((m) => m.loadDay(state.day)),
    });
    return [err];
  }
  const out = [];
  if (eventsFailed) {
    out.push(paneError({ title: t("activity.loadFailedTitle"), message: eventsFailed, onRetry: fetchEvents }));
  }
  const feed = buildFeed(events);
  if (!feed.length) {
    out.push(emptyNote(state.movementOnly || state.groupMembers || state.deviceFilter ? "activity.emptyFiltered" : "activity.empty"));
    return out;
  }
  const list = document.createElement("ol");
  list.className = "fp-act-list";
  list.setAttribute("aria-label", t("activity.listLabel"));
  for (const line of feed.slice(0, shown)) list.appendChild(renderLine(line, openLine));
  out.push(list);
  if (feed.length > shown) out.push(moreRow(feed.length));
  return out;
}

function render() {
  if (!root) return;
  const key = keyNow();
  if (key !== viewKey) { viewKey = key; shown = PAGE_SIZE; }
  root.replaceChildren(...body());
}

async function fetchEvents() {
  const day = state.day;
  if (!day || state.locked) return;
  const mine = ++seq;
  const gen = state.lockGeneration;
  const { since, until } = dayBounds(day);
  const qs = new URLSearchParams({ since, until, limit: "1000" });
  try {
    const rows = await api(`/api/groups/events?${qs}`);
    if (mine !== seq || gen !== state.lockGeneration) return;
    events = Array.isArray(rows) ? rows : [];
    eventsFailed = null;
  } catch (err) {
    if (mine !== seq || gen !== state.lockGeneration || err.message === "Locked") return;
    events = [];
    eventsFailed = err.message || t("common.unknownError");
  }
  eventsDay = day;
  render();
}

/** A tracks redraw: draw from state now; fetch events only when the day moved. */
function onTracksRendered() {
  if (!root) return;
  render();
  if (state.day && state.day !== eventsDay) fetchEvents();
}

let wired = false;
function wire() {
  if (wired) return;
  wired = true;
  window.addEventListener("findplus:tracks-rendered", onTracksRendered);
  document.addEventListener("fp:person-colours", () => render());
}

export function mountActivity(container) {
  root = container;
  wire();
  container.classList.add("fp-act");
  maybeRefreshPersonColours();
  render();
  if (state.day && state.day !== eventsDay) fetchEvents();
}

export function refreshActivity() {
  maybeRefreshPersonColours();
  fetchEvents();
}

/** Lock: names, places and times must not outlive the lock screen. */
export function purgeActivity() {
  seq += 1;
  events = [];
  eventsDay = null;
  eventsFailed = null;
  shown = PAGE_SIZE;
  viewKey = "";
  if (root) root.replaceChildren();
}
