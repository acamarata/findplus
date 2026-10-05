/*
 * The Latest list's data: who is shown, in what order, and what is known.
 *
 * Purpose    : Build the one list the Latest tab draws: people first (alphabetical,
 *              each with the person engine's own "where" answer), then the trackers
 *              that belong to no person, most recently seen first.
 * Inputs     : GET /api/people and GET /api/people/{id}/now (existing endpoints);
 *              state.devices (labels, icons, colours, current places, last seen).
 * Outputs    : loadLatest() -> { people: [{person, now, stale}], trackers: [device] },
 *              ageMinutes(device), placeName(device), trackerName(device).
 * Constraints: Reads only. A failed "now" lookup leaves that person without a
 *              sentence rather than failing the list. Nothing is cached here, so a
 *              lock leaves nothing behind.
 */
"use strict";

import { state, displayName } from "./state.js";
import { fetchNow, fetchPeople } from "./person_api.js";
import { labelMap, visibleDevices } from "./device_label.js";

/** Whole minutes since the tracker's last sighting, or null when it has none. */
export function ageMinutes(device) {
  if (!device || !device.observation_count || !device.last_seen_at) return null;
  const then = Date.parse(device.last_seen_at);
  return Number.isNaN(then) ? null : Math.max(0, Math.floor((Date.now() - then) / 60000));
}

/** The saved place the tracker is inside right now, or "". */
export function placeName(device) {
  const inside = (device && device.presence) || [];
  return inside.length ? inside[0].place_name || "" : "";
}

/** The label a row prints: the owner's label or provider name, with an id tail only on a clash. */
export function trackerName(device) {
  return labelMap(visibleDevices()).get(device.device_id) || displayName(device) || device.device_id;
}

/** A person is dimmed when the engine has nothing current: unknown, never seen, or every tracker stale. */
export function isStale(person, now) {
  if (!now) return true;
  if (now.confidence === "unknown" || now.age_minutes == null) return true;
  const stale = (now.stale || []).length;
  return stale > 0 && stale >= (person.trackers || []).length;
}

async function nowFor(person) {
  try {
    return await fetchNow(person.id);
  } catch (_) {
    return null;
  }
}

const byRecent = (a, b) => (Date.parse(b.last_seen_at) || 0) - (Date.parse(a.last_seen_at) || 0);

/** People (alphabetical) with their "now", and the trackers no person owns (newest first). */
export async function loadLatest() {
  const list = await fetchPeople().catch(() => []);
  const people = [...list].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  const nows = await Promise.all(people.map(nowFor));
  const owned = new Set(people.flatMap((p) => (p.trackers || []).map((tr) => tr.device_id)));
  const trackers = visibleDevices(state.devices).filter((d) => !owned.has(d.device_id)).sort(byRecent);
  return { people: people.map((person, i) => ({ person, now: nows[i], stale: isStale(person, nows[i]) })), trackers };
}
