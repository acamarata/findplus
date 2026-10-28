/*
 * Tracker focus: show one tracker in the side panel and on the map.
 *
 * Purpose    : Clicking a tracker (a Latest row, an Activity line, a map popup's
 *              "Show only this") focuses it: the Latest tab shows a header (Back
 *              "All", badge, name, Edit) and a Story | Sightings switch over the
 *              existing day body, and the map draws only that tracker. Back puts
 *              the previous tab, filter and map back.
 * Inputs     : focusTracker(deviceId, {pointId}); window event
 *              `findplus:focus-tracker` (detail {device_id, point_id?}); the hash
 *              `#/tracker/<device_id>` (optional `?point=<id>`).
 * Outputs    : focusTracker, unfocus, focusedDevice, trackerRoute, trackerHref,
 *              wireTrackerFocus. The URL becomes `#/tracker/<id>` while focused.
 * Constraints: The map filter is the dashboard's own device filter
 *              (state.deviceFilter + reload), set without being remembered, and a
 *              group filter that would hide the tracker is lifted until Back. Leaving
 *              Latest by any other route (another tab, the Person page) ends the
 *              focus quietly and restores the filter.
 */
"use strict";

import { $, state } from "./state.js";
import { activeTab, switchTab } from "./panel_tabs.js";
import { drawFocus, drawList } from "./tracker_focus_view.js";
import { openDeviceEditor } from "./latest_rows.js";

const ROUTE = /^#\/tracker\/([^/?#]+)(?:\?point=(\d+))?$/;
let focus = null;
let wired = false;

/** `{deviceId, pointId}` for a `#/tracker/<id>` hash, else null. */
export function trackerRoute(hash) {
  const m = ROUTE.exec(hash || "");
  if (!m) return null;
  let deviceId;
  try { deviceId = decodeURIComponent(m[1]); } catch (_) { return null; }
  return { deviceId, pointId: m[2] ? Number(m[2]) : null };
}

export const trackerHref = (id) => `#/tracker/${encodeURIComponent(id)}`;
/** The device id in focus, or null. */
export const focusedDevice = () => (focus ? focus.deviceId : null);

const reloadAll = () => import("./main.js").then((m) => m.reload());
const setHash = (hash) => { try { history.replaceState(null, "", hash); } catch (_) { /* sandboxed */ } };

function setFilter(value) {
  state.deviceFilter = value;
  const select = $("device-filter");
  if (select) { select.value = value; if (select.value !== value) select.value = ""; }
}

function deviceFor(id) {
  return state.devices.find((d) => d.device_id === id) || { device_id: id, name: id, icon: "none", color: null, label: null };
}

function render(view) {
  const container = $("tab-latest");
  if (!container || !focus) return;
  const device = deviceFor(focus.deviceId);
  focus.view = view;
  drawFocus(container, device, view, {
    onBack: () => unfocus(),
    onEdit: () => openDeviceEditor(deviceFor(focus.deviceId), () => focus && render(focus.view)),
    onView: (next) => render(next),
  });
}

/** Show the focus view if a focus is active; called by the Latest tab each time it mounts. */
export function showFocusIfActive() {
  if (focus) render(focus.view);
  return Boolean(focus);
}

async function leavePerson() {
  if (state.personView) await import("./person_route.js").then((m) => m.hidePerson());
}

/** Focus `deviceId`; with `pointId`, open Sightings and select that sighting. */
export async function focusTracker(deviceId, { pointId = null } = {}) {
  if (!deviceId || state.locked) return;
  await leavePerson();
  const view = pointId ? "raw" : "story";
  if (focus && focus.deviceId === deviceId) {
    render(view);
  } else {
    const prevTab = activeTab() === "latest" || !activeTab() ? "latest" : activeTab();
    const group = state.groupMembers && !state.groupMembers.has(deviceId) ? state.groupMembers : null;
    focus = { deviceId, prevTab: focus ? focus.prevTab : prevTab, prevFilter: focus ? focus.prevFilter : state.deviceFilter, prevGroup: focus ? focus.prevGroup : group, view };
    if (group) state.groupMembers = null;
    setFilter(deviceId);
    switchTab("latest", { remember: false });
    render(view);
    setHash(trackerHref(deviceId));
    await reloadAll();
  }
  if (pointId) {
    const { selectPoint } = await import("./timeline.js");
    selectPoint(pointId, true);
  }
}

function restore(prev) {
  setFilter(prev.prevFilter || "");
  if (prev.prevGroup) state.groupMembers = prev.prevGroup;
  import("./trips_view.js").then((m) => m.forceDayView(null));
}

/** End the focus. `back` (default) also returns to the tab the user came from. */
export async function unfocus({ back = true } = {}) {
  if (!focus) return;
  const prev = focus;
  focus = null;
  restore(prev);
  const container = $("tab-latest");
  if (container) drawList(container);
  if (back) {
    setHash(`#/${prev.prevTab}`);
    switchTab(prev.prevTab, { remember: false });
  }
  await reloadAll();
}

/** Lock purge: forget the focus without touching the page (the lock screen is up). */
export function dropFocus() {
  if (!focus) return;
  const prev = focus;
  focus = null;
  state.deviceFilter = prev.prevFilter || "";
  if (prev.prevGroup) state.groupMembers = prev.prevGroup;
  if (state.resume && state.resume.deviceFilter === prev.deviceId) state.resume.deviceFilter = state.deviceFilter;
  if (trackerRoute(window.location.hash)) setHash(`#/${prev.prevTab}`);
}

/** Listen once for the focus event and for tab changes that end a focus. */
export function wireTrackerFocus() {
  if (wired) return;
  wired = true;
  window.addEventListener("findplus:focus-tracker", (e) => {
    const d = (e.detail || {});
    focusTracker(d.device_id, { pointId: d.point_id || null }).catch((err) => console.warn("focus failed", err));
  });
  window.addEventListener("findplus:day-view", (e) => { if (focus && e.detail) render(e.detail.view); });
  window.addEventListener("findplus:tab-changed", (e) => {
    if (focus && e.detail && e.detail.tab !== "latest") {
      if (trackerRoute(window.location.hash)) setHash(`#/${e.detail.tab}`);
      unfocus({ back: false }).catch(() => {});
    }
  });
}
