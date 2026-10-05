/*
 * Which person (or pet) a tracker belongs to, and that person's colour.
 *
 * Purpose    : The map ring, the Latest rows and the Activity dots all need
 *              "whose tracker is this, and what is their colour?" for a
 *              device id. One cached lookup answers it for all of them, so no
 *              surface fetches /api/people on its own.
 * Inputs     : GET /api/people (people with their trackers).
 * Outputs    : personForDevice(id) -> {id, name, kind, color} | null,
 *              personColour(id) -> "#rrggbb" | null, refreshPersonColours(),
 *              and a `fp:person-colours` event on document after a refresh
 *              that changed something.
 * Constraints: Reads only. A failed or locked fetch keeps the old answer and
 *              never throws. Colours are accepted only as lowercase #rrggbb, so
 *              they are safe to put in markup. purgePersonColours() empties the
 *              cache on lock (names must not outlive the lock screen).
 * Reuse      : map_marker.js (ring), the Latest and Activity rows, person_editor.js
 *              (calls refreshPersonColours after a save).
 */
"use strict";

import { api } from "./api.js";

export const PERSON_COLOURS_EVENT = "fp:person-colours";

/** A refresh younger than this is not repeated by maybeRefreshPersonColours(). */
const FRESH_MS = 15000;
const HEX = /^#[0-9a-f]{6}$/;

let byDevice = new Map();
let loadedAt = 0;
let inFlight = null;

/** The person a device belongs to, or null (a tracker with no person, or not loaded yet). */
export function personForDevice(deviceId) {
  return byDevice.get(deviceId) || null;
}

/** The person's colour for a device, or null when the tracker belongs to nobody. */
export function personColour(deviceId) {
  const person = byDevice.get(deviceId);
  return person ? person.color : null;
}

function indexPeople(people) {
  const next = new Map();
  for (const person of people) {
    if (!HEX.test(person.color || "")) continue;
    const entry = { id: person.id, name: person.name, kind: person.kind, color: person.color };
    for (const tracker of person.trackers || []) next.set(tracker.device_id, entry);
  }
  return next;
}

function sameIndex(a, b) {
  if (a.size !== b.size) return false;
  for (const [key, p] of a) {
    const q = b.get(key);
    if (!q || q.id !== p.id || q.color !== p.color || q.name !== p.name) return false;
  }
  return true;
}

/** Fetch /api/people now. Resolves true when the answer changed (an event also fires). */
export function refreshPersonColours() {
  if (inFlight) return inFlight;
  inFlight = api("/api/people")
    .then((people) => {
      const next = indexPeople(Array.isArray(people) ? people : []);
      const changed = !sameIndex(byDevice, next);
      byDevice = next;
      loadedAt = Date.now();
      if (changed) document.dispatchEvent(new CustomEvent(PERSON_COLOURS_EVENT));
      return changed;
    })
    .catch(() => false)
    .finally(() => { inFlight = null; });
  return inFlight;
}

/** Refresh unless a recent answer is already held; safe to call on every map draw. */
export function maybeRefreshPersonColours() {
  if (inFlight || Date.now() - loadedAt < FRESH_MS) return;
  refreshPersonColours();
}

/** Lock: drop every name and colour. */
export function purgePersonColours() {
  byDevice = new Map();
  loadedAt = 0;
}
