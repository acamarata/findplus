/*
 * The day story pane: which tracker, which state, selection, and the map link.
 *
 * Purpose    : Decide what the dashboard's right pane and map show for one
 *              tracker's day: the day story (stays and trips), the plain
 *              list of every sighting, or a message. "Day story" is the default
 *              once a tracker is picked; the choice is remembered once the
 *              person makes it. The raw list is exactly what it was before.
 * Inputs     : state.timeline (tracks and fixes), state.day, state.deviceFilter,
 *              state.groupMembers, /api/trips through trips_data.js.
 * Outputs    : renderStoryPane() (called by renderTracks), storyMapRender()
 *              (called by renderMap), wireStory(), hideStory(), purgeStory().
 * Constraints: Trackers are never merged: one tracker's day at a time; a group
 *              adds lanes that sit under each other, nothing more. A fetch that
 *              finishes after a lock or a newer selection is dropped. On lock
 *              purgeStory() leaves no coordinate, time or place name in the DOM.
 */
"use strict";

import { $, state, visibleTracks } from "./state.js";
import { renderMap } from "./map.js";
import { renderTracks } from "./track_blocks.js";
import { emptyDayState } from "./dashboard_empty.js";
import { cachedTrips, loadTrips, purgeTripsData, refreshRouting, routeOf, routingOn } from "./trips_data.js";
import { buildItems, hasStory } from "./trips_format.js";
import { drawStory, frame, clearStoryDrawn } from "./trips_map.js";
import { markList, wireStoryKeys } from "./trips_list.js";
import { markStrip, lanes } from "./trips_strip.js";
import { storyBody, nameOf } from "./trips_pane.js";
import { laneLabel } from "./person_links.js";
import { emptyTitle, failure, skeleton, sparse } from "./trips_states.js";
import { purgeRoads, queueRoutes, roadsWanted, syncRouteNote, syncRoadsUi, wireRoads } from "./trips_roads.js";

const PREF_KEY = "findplus.dayView";
let pref = readPref();
/** A view the shell imposes without touching the remembered choice (the Activity tab forces "raw"). */
let forced = null;
let pickDevice = null;
let selectedId = null;
let showInside = false;
let pendingFocus = false;
let current = null;
let last = null;
let viewKey = "";
let seq = 0;
const laneFailed = new Set();

function readPref() {
  try {
    const v = localStorage.getItem(PREF_KEY);
    return v === "story" || v === "raw" ? v : null;
  } catch (_) {
    return null;
  }
}

function writePref(value) {
  pref = value;
  try { localStorage.setItem(PREF_KEY, value); } catch (_) { /* private mode */ }
}

const sigOf = (tr) => `${tr.points.length}:${tr.points[tr.points.length - 1].id}`;
const withPoints = () => visibleTracks(state.timeline.tracks).filter((tr) => tr.points.length);

function focusTrack(list) {
  const want = state.deviceFilter || pickDevice;
  return list.find((tr) => tr.device_id === want) || list[0] || null;
}

/** What the pane should show right now, without changing anything. */
function resolve() {
  if (state.locked || !state.timeline) return { shown: "raw" };
  const list = withPoints();
  const track = focusTrack(list);
  const mode = forced ?? pref;
  const auto = mode === null;
  if (mode === "raw" || (auto && !(track && state.deviceFilter))) return { shown: "raw", list, track };
  if (!track) return { shown: auto ? "raw" : "empty", list, track };
  const sig = sigOf(track);
  const fresh = cachedTrips(track.device_id, state.day, sig);
  if (fresh) last = { device: track.device_id, day: state.day, payload: fresh };
  // A refresh with a new fix keeps the old story on screen until the new one arrives.
  const keep = last && last.device === track.device_id && last.day === state.day ? last.payload : null;
  const payload = fresh || keep;
  const failed = current && current.error && current.device === track.device_id && current.day === state.day && current.sig === sig;
  const base = { list, track, sig, payload, fresh: Boolean(fresh) };
  if (payload) return { ...base, shown: hasStory(payload) ? "story" : auto ? "raw" : "sparse" };
  if (failed) return { ...base, shown: auto ? "raw" : "error", error: current.error };
  return { ...base, shown: auto ? "wait" : "loading" };
}

/** Start (once per tracker, day and fix signature) the fetch the pane waits on. */
function startLoad(view) {
  const { track, sig } = view;
  const same = current && current.device === track.device_id && current.day === state.day && current.sig === sig;
  if (same) return;
  const mine = ++seq;
  const gen = state.lockGeneration;
  current = { device: track.device_id, day: state.day, sig, error: null };
  loadTrips(track.device_id, state.day, sig).then(
    () => { if (mine === seq && gen === state.lockGeneration) redraw(true); },
    (err) => {
      if (mine !== seq || gen !== state.lockGeneration || err.status === 401) return;
      current.error = err;
      redraw(true);
    }
  );
}

/** Rebuild the pane and the map from what is known. */
function redraw(fit) {
  renderTracks();
  renderMap({ fit });
}

function syncSwitch(shown) {
  const on = shown === "raw" ? "raw" : "story";
  $("view-story").setAttribute("aria-pressed", String(on === "story"));
  $("view-raw").setAttribute("aria-pressed", String(on === "raw"));
}

/** Hide the story and clear what the map drew for it. */
export function hideStory() {
  const root = $("story");
  if (root) { root.hidden = true; root.replaceChildren(); }
  clearStoryDrawn();
  syncRouteNote(false);
}

function emptyPane(day) {
  const node = emptyDayState();
  const title = node.querySelector(".empty-title");
  if (title && ["quiet", "pending"].includes(node.dataset.emptyDay)) title.textContent = emptyTitle(day);
  return node;
}

function bodyCtx(view) {
  return {
    ...view, day: state.day, selectedId, showInside, fixedDevice: Boolean(state.deviceFilter),
    onPick: (id) => selectItem(id), onPickDevice: (id) => chooseDevice(id),
    onInside: (on) => { showInside = on; renderMap({ fit: false }); },
  };
}

/** What goes inside #story for each state. */
function paneNode(view) {
  const retry = () => { current = null; redraw(true); };
  if (view.shown === "story") return storyBody(bodyCtx(view));
  if (view.shown === "sparse") return sparse(view.track.points.length, () => setView("raw"));
  if (view.shown === "error") return failure(view.error, retry);
  if (view.shown === "empty") return emptyPane(state.day);
  return skeleton();
}

/** Called by renderTracks() after it cleared #tracks: true when the story took over. */
export function renderStoryPane() {
  const root = $("story");
  const view = resolve();
  syncSwitch(view.shown);
  if (view.shown === "raw") { hideStory(); syncRoadsUi(false); return false; }
  const key = view.track ? `${view.track.device_id}|${state.day}` : "";
  if (key !== viewKey) { viewKey = key; selectedId = null; }
  if (view.track && !view.fresh) startLoad(view);
  if (routingOn() === null) learnRouting();
  syncRoadsUi(view.shown === "story");
  if (view.shown === "wait") { hideStory(); return true; }
  root.hidden = false;
  root.replaceChildren(paneNode(view));
  if (view.shown === "story") afterBody(view, root);
  return true;
}

/** After the body is in the DOM: selection marks, lanes, and road routes. */
function afterBody(view, root) {
  const items = buildItems(view.payload);
  if (selectedId && !items.some((i) => i.id === selectedId)) selectedId = null;
  markList(root, selectedId);
  markStrip(root, selectedId);
  if (state.groupMembers && view.list.length > 1) fillLanes(view, root);
  startRoutes(view);
}

function startRoutes(view) {
  if (!roadsWanted()) return;
  const first = selectedId && selectedId.startsWith("t") ? selectedId : null;
  queueRoutes(view.track.device_id, state.day, view.payload.trips, first, () => renderMap({ fit: false }));
}

/** The family lanes: one bar per visible member, filled as each member's day arrives. */
function fillLanes(view, root) {
  const slot = root.querySelector(".lanes-slot");
  const gen = state.lockGeneration;
  const paint = () => {
    if (state.lockGeneration !== gen || !slot.isConnected) return;
    const members = view.list.map((tr) => ({
      device_id: tr.device_id,
      name: laneLabel(tr.device_id, nameOf(tr)),
      payload: cachedTrips(tr.device_id, state.day, sigOf(tr)),
      failed: laneFailed.has(tr.device_id),
    }));
    slot.replaceChildren(lanes(members, state.day, view.track.device_id, { onMember: chooseDevice, onRetry: (id) => { laneFailed.delete(id); fillLanes(view, root); } }));
  };
  paint();
  view.list.filter((tr) => !cachedTrips(tr.device_id, state.day, sigOf(tr))).forEach((tr) => {
    laneFailed.delete(tr.device_id);
    loadTrips(tr.device_id, state.day, sigOf(tr)).then(paint, (err) => { if (err.status !== 401) { laneFailed.add(tr.device_id); paint(); } });
  });
}

function chooseDevice(id) {
  pickDevice = id;
  selectedId = null;
  redraw(true);
}

/** Select a stay or trip: mark it everywhere, then move the map to it. */
function selectItem(id) {
  selectedId = id;
  pendingFocus = true;
  const root = $("story");
  markList(root, id);
  markStrip(root, id);
  const row = root.querySelector(`.story-item[data-id="${id}"]`);
  if (row) row.scrollIntoView({ block: "nearest" });
  renderMap({ fit: false });
  if (id.startsWith("t")) startRoutes(resolve());
}

function clearSelection() {
  selectedId = null;
  markList($("story"), null);
  markStrip($("story"), null);
  renderMap({ fit: false });
}

/** Called by renderMap(): draw the story layers; false means "draw the plain tracks". */
export function storyMapRender({ fit }) {
  const view = resolve();
  if (state.legend) { state.legend.remove(); state.legend = null; }
  if (view.shown === "raw" || view.shown === "sparse" || view.shown === "error") { clearStoryDrawn(); syncRouteNote(false); return false; }
  if (view.shown !== "story") { clearStoryDrawn(); syncRouteNote(false); return true; }
  const routes = new Map();
  view.payload.trips.forEach((trip) => { const r = routeOf(view.track.device_id, state.day, trip.id); if (r) routes.set(trip.id, r); });
  const out = drawStory({
    payload: view.payload, routes, selectedId, showInside, fixes: view.track.points, onPick: selectItem,
  });
  syncRouteNote([...routes.values()].some((r) => r.style === "solid"));
  if (pendingFocus && out.focus) frame(out.focus);
  else if (fit) frame(out.bounds);
  pendingFocus = false;
  return true;
}

/**
 * Impose "raw" (or null to release) without changing the remembered Day story /
 * Every sighting choice. Used by the shell's Activity adapter; redraws on change.
 */
export function forceDayView(value) {
  if (forced === value) return;
  forced = value;
  if (state.timeline) redraw(true);
}

function setView(value) {
  writePref(value);
  redraw(true);
}

function learnRouting() {
  refreshRouting().then(() => syncRoadsUi(resolve().shown === "story"));
}

/** Wire the Day story / Every sighting switch, the arrow keys and the roads box. */
export function wireStory() {
  $("view-story").addEventListener("click", () => setView("story"));
  $("view-raw").addEventListener("click", () => setView("raw"));
  wireStoryKeys($("story"), clearSelection);
  wireRoads(() => { syncRoadsUi(true); renderMap({ fit: false }); startRoutes(resolve()); });
  // Back from Settings (a routing server may have been set): look again.
  window.addEventListener("focus", () => { if (!state.locked) learnRouting(); });
}

/** Lock purge: no coordinate, time, tracker or place name may stay anywhere. */
export function purgeStory() {
  hideStory();
  purgeTripsData();
  purgeRoads();
  current = null;
  selectedId = null;
  pickDevice = null;
  pendingFocus = false;
  laneFailed.clear();
  seq += 1;
  last = null;
  viewKey = "";
}
