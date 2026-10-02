/*
 * The Person page: loads one person's day and draws every part of it.
 *
 * Purpose    : `#/person/<id>?date=...` in one place: the header and "now"
 *              sentence, the day summary, the map (one line per tracker), the
 *              day story with family lanes, the tracker list and the actions.
 *              A line of the summary, a story row or a map stay moves all three
 *              to the same moment.
 * Inputs     : A person id and a local day. Reads /api/people/{id} (+ /now,
 *              /day, /left-behind), /api/timeline?group_id= and /api/trips.
 * Outputs    : The page DOM, map layers on the shared dashboard map, and
 *              purge() for lock.js.
 * Constraints: A response that arrives after a newer request, a different
 *              person or a lock is dropped. purge() leaves no name, time or
 *              coordinate in the DOM, the map layers or the caches. Trackers
 *              are never merged: one line, one lane, one story per tracker.
 */
"use strict";

import { $, state, colorFor, todayLocal } from "./state.js";
import { t } from "./i18n.js";
import { uniqueLabel } from "./device_label.js";
import { loadTrips } from "./trips_data.js";
import { markList } from "./trips_list.js";
import { markStrip } from "./trips_strip.js";
import { fetchDay, fetchLeftBehind, fetchNow, fetchPerson, fetchTimeline, normalizeDay } from "./person_api.js";
import { syncDateBar } from "./person_datebar.js";
import { renderHead, clearHead } from "./person_head.js";
import { renderActions, clearActions } from "./person_actions.js";
import { emptyDayNode, errorNode, loadingNode, notFoundNode, partialNote } from "./person_states.js";
import { summaryCard, markLine } from "./person_summary.js";
import { storyCard } from "./person_story.js";
import { trackersCard } from "./person_trackers.js";
import { drawPerson, frameBounds, highlight, showMapOnPhone } from "./person_map.js";
import { focusMoment } from "./person_focus.js";
import { setShowSuspect, showSuspect, suspectToggle } from "./suspect_pref.js";
import { honestyFooter } from "./person_notes.js";
import { purgePeopleCache } from "./person_links.js";
import { purge as purgeSuggestions } from "./people_suggest.js";
import { purgeLeftBehind } from "./left_behind_chips.js";

const page = fresh();
let layers = null;

function fresh() {
  return { id: null, date: null, seq: 0, person: null, now: null, day: null, tracks: [], payloads: new Map(), failed: new Set(), episodes: [], focusId: null, selectedId: null, notes: [] };
}

/** The layer groups the page draws into, created on first use. */
export function ensureLayers() {
  if (!layers && state.map) layers = { draw: L.layerGroup().addTo(state.map), mark: L.layerGroup().addTo(state.map) };
  return layers;
}

/** Remove the page's map layers (the page is closing). */
export function dropLayers() {
  if (!layers) return;
  layers.draw.remove();
  layers.mark.remove();
  layers = null;
}

const setStatus = (text, kind) => {
  const el = $("person-status");
  el.textContent = text;
  el.className = `person-status${kind ? ` person-status--${kind}` : ""}`;
};
const setBody = (...nodes) => $("person-body").replaceChildren(...nodes);

function nameOf(deviceId) {
  const device = (state.devices || []).find((d) => d.device_id === deviceId);
  const tracker = page.person && page.person.trackers.find((x) => x.device_id === deviceId);
  return uniqueLabel(device) || (tracker && tracker.name) || deviceId;
}

/** Trackers ordered best sighting first, then by name. */
function ordered(person, now) {
  const lead = now && now.lead_device_id;
  const rank = (tr) => (tr.device_id === lead ? 0 : 1);
  return [...person.trackers].sort((a, b) => rank(a) - rank(b) || nameOf(a.device_id).localeCompare(nameOf(b.device_id)));
}

const hasPoints = () => page.tracks.some((tr) => tr.points.length);

function mapCtx() {
  return {
    tracks: page.tracks, trips: new Map([...page.payloads].filter(([, p]) => p)), leadId: page.focusId, showSuspect: showSuspect(),
    colorOf: (id) => ((state.devices || []).find((d) => d.device_id === id) || {}).color || colorFor(id), nameOf, onPickStay: pickItem,
  };
}

function drawMap(fit) {
  const l = ensureLayers();
  if (!l) return;
  const out = drawPerson(l.draw, mapCtx());
  l.mark.clearLayers();
  if (fit) frameBounds(out.bounds);
}

function storyCtx() {
  const trackers = ordered(page.person, page.now);
  return {
    trackers, payloads: page.payloads, failed: page.failed, day: page.date, name: page.person.name, focusId: page.focusId, nameOf,
    onPick: (id) => pickItem(page.focusId, id), onMember: (id) => { page.focusId = id; page.selectedId = null; renderStory(); drawMap(false); },
    onRetry: (id) => { page.failed.delete(id); loadOne(id).then(renderStory); renderStory(); },
  };
}

function renderStory() {
  const old = $("person-body").querySelector(".person-story");
  const next = storyCard(storyCtx());
  // The card is rebuilt on every pick: keep keyboard focus on the same row.
  const held = document.activeElement && document.activeElement.closest(".story-item");
  const heldId = held ? held.dataset.id : null;
  if (old) old.replaceWith(next);
  if (heldId) next.querySelector(`.story-item[data-id="${heldId}"]`)?.focus({ preventScroll: true });
  markList(next, page.selectedId);
  const strip = next.querySelector(".strip");
  if (strip) markStrip(strip, page.selectedId);
}

/** Select a stay or trip of `device` and move the map to it. */
function pickItem(device, id) {
  page.focusId = device;
  page.selectedId = id;
  renderStory();
  showMapOnPhone();
  const payload = page.payloads.get(device);
  const item = payload && [...payload.stays, ...payload.trips].find((x) => x.id === id);
  if (!item) return;
  const l = ensureLayers();
  if (item.points) {
    const b = L.latLngBounds(item.points.map((p) => [p.latitude, p.longitude]));
    highlight(l.mark, null);
    frameBounds(b);
  } else {
    highlight(l.mark, [item.latitude, item.longitude], item.radius_meters);
    frameBounds(L.latLng(item.latitude, item.longitude).toBounds(Math.max(item.radius_meters, 60) * 2));
  }
}

/** Escape in the story list: let go of the picked row and the ring on the map. */
export function clearSelection() {
  page.selectedId = null;
  renderStory();
  if (layers) layers.mark.clearLayers();
}

function onLine(line) {
  markLine($("person-body"), line.id);
  const hit = focusMoment(line, { payloads: page.payloads, tracks: page.tracks, focusId: page.focusId });
  if (!hit) return;
  showMapOnPhone();
  if (hit.item) pickItem(hit.device, hit.item.id);
  else if (hit.point) { highlight(ensureLayers().mark, hit.point, 40); state.map.setView(hit.point, Math.max(state.map.getZoom(), 16)); }
}

/** The summary's "(show)": switch the faint sightings on and frame them. */
function showWrong() {
  setShowSuspect(true);
  const box = $("person-suspect");
  if (box) box.checked = true;
  drawMap(false);
  const wrong = page.tracks.flatMap((tr) => tr.points.filter((p) => p.suspect));
  if (wrong.length) frameBounds(L.latLngBounds(wrong.map((p) => [p.lat !== undefined ? p.lat : p.latitude, p.lon !== undefined ? p.lon : p.longitude])));
}

/** {date, last} for a day before today (the header then says "On <date>"), else null. */
function pastOf() {
  if (!page.date || page.date >= todayLocal()) return null;
  const lines = (page.day && page.day.lines) || [];
  const last = lines.length ? lines[lines.length - 1].text : "";
  return { date: page.date, last };
}

function failedNames() {
  return [...page.failed].map(nameOf);
}

function renderBody() {
  const nodes = [];
  if (page.failed.size || page.notes.length) nodes.push(partialNote(page.person.name, [...failedNames(), ...page.notes]));
  nodes.push(summaryCard(page.person.name, page.day, onLine, showWrong));
  if (!hasPoints()) nodes.push(emptyDayNode(page.person.name, page.date));
  else {
    const toggle = document.createElement("div");
    toggle.className = "person-map-controls";
    toggle.append(suspectToggle("person-suspect", () => drawMap(false)), mapNote());
    nodes.push(toggle, storyCard(storyCtx()));
  }
  nodes.push(trackersCard({ ...storyCtx(), now: page.now, episodes: page.episodes, fixes: new Map(((page.day && page.day.trackers) || []).map((x) => [x.device_id, x.fixes])), name: page.person.name, devices: state.devices, leadId: page.now && page.now.lead_device_id, onChanged: () => reload() }), honestyFooter());
  setBody(...nodes);
  markList($("person-body"), page.selectedId);
  state.map.getContainer().setAttribute("aria-label", t("person.map.label", { name: page.person.name }));
}

function mapNote() {
  const p = document.createElement("p");
  p.className = "person-hint";
  p.textContent = t("person.map.legend");
  return p;
}

async function loadOne(device) {
  try {
    page.payloads.set(device, await loadTrips(device, page.date, String(page.seq)));
  } catch (err) {
    if (err.status === 401) throw err;
    page.failed.add(device);
  }
}

const quiet = (promise) => promise.then((v) => ({ v }), (e) => ({ e }));

/** Fetch and draw `id` on `date`. Resolves when the page is drawn (or dropped). */
export async function loadPerson(id, date) {
  const mine = ++page.seq;
  const gen = state.lockGeneration;
  const alive = () => mine === page.seq && gen === state.lockGeneration && !state.locked;
  if (page.id !== id) Object.assign(page, fresh(), { seq: mine });
  Object.assign(page, { id, date, day: null, payloads: new Map(), failed: new Set(), notes: [], selectedId: null });
  syncDateBar(id, date);
  setStatus("", "");
  setBody(loadingNode(page.person && page.person.name));
  const retry = () => loadPerson(id, date);
  const person = await quiet(fetchPerson(id));
  if (!alive()) return;
  if (person.e) return fail(person.e, retry);
  page.person = person.v;
  renderHead(page.person, null, pastOf());
  renderActions(page.person, date, setStatus);
  const [now, day, tl, lb] = await Promise.all([fetchNow(id), fetchDay(id, date), fetchTimeline(id, date), fetchLeftBehind(id)].map(quiet));
  if (!alive()) return;
  if (tl.e) return fail(tl.e, retry);
  Object.assign(page, { now: now.v || null, day: day.v ? normalizeDay(day.v) : null, tracks: tl.v, episodes: lb.v || [] });
  if (now.e) page.notes.push(t("person.state.noNow"));
  renderHead(page.person, page.now, pastOf());
  page.focusId = ordered(page.person, page.now)[0]?.device_id || null;
  await Promise.all(page.person.trackers.map((tr) => loadOne(tr.device_id)));
  if (!alive()) return;
  renderBody();
  drawMap(true);
}

function fail(err, retry) {
  if (err.status === 404) { clearHead(); clearActions(); setBody(notFoundNode()); return; }
  setBody(errorNode(page.person && page.person.name, err, retry));
}

/** Reload the page in place (a tracker role changed, or the person was edited). */
export function reload() {
  return page.id ? loadPerson(page.id, page.date) : Promise.resolve();
}

export const currentId = () => page.id;

/** Lock purge (also called for the suggestions panel and left-behind notices): nothing about a person, a day or a place may survive. */
export function purge() {
  const gen = page.seq + 1;
  Object.assign(page, fresh(), { seq: gen });
  purgePeopleCache();
  purgeSuggestions();
  purgeLeftBehind();
  import("./people_replay.js").then((m) => m.purgeReplay()).catch(() => {});
  import("./person_editor.js").then((m) => m.purgePersonEditor()).catch(() => {});
  import("./settings_people.js").then((m) => m.purgePeopleSettings()).catch(() => {});
  clearHead();
  clearActions();
  setStatus("", "");
  setBody();
  const date = $("person-date");
  if (date) date.value = "";
  if (layers) { layers.draw.clearLayers(); layers.mark.clearLayers(); }
  if (state.map) state.map.getContainer().setAttribute("aria-label", t("map.label"));
}
