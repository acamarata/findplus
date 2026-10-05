/*
 * The All Activity feed as data: one merged, newest-first list for a day.
 *
 * Purpose    : Turn the day's timeline (every tracker's sightings) and the
 *              people's arrival/departure events into one flat list of lines,
 *              so the pane only has to draw them.
 * Inputs     : state.timeline, visibleTracks() and visiblePoints() (the same
 *              Show / Group / movement / suspect filters the map and the old
 *              list use), plus the event rows from GET /api/groups/events.
 * Outputs    : buildFeed(events) -> [{kind: "sighting"|"event", at, ...}],
 *              dayBounds(day) -> {since, until} ISO strings for the events call.
 * Constraints: Pure reads; no DOM, no fetch. A person event is kept only for a
 *              person who owns a tracker the filters currently allow.
 */
"use strict";

import { state, visibleTracks } from "./state.js";
import { visiblePoints, deviceForTrack } from "./map.js";
import { personById, personForDevice } from "./person_colours.js";
import { uniqueLabel } from "./device_label.js";

/** The local day as the since/until pair the events endpoint takes. */
export function dayBounds(day) {
  const since = new Date(`${day}T00:00:00`);
  const until = new Date(`${day}T23:59:59.999`);
  return { since: since.toISOString(), until: until.toISOString() };
}

function sightingLines(track) {
  const device = deviceForTrack(track);
  const label = uniqueLabel(device) || track.device_name || track.device_id;
  const person = personForDevice(track.device_id);
  return visiblePoints(track).map((point) => ({
    kind: "sighting",
    at: Date.parse(point.observed_at),
    iso: point.observed_at,
    id: `p${point.id}`,
    point,
    device,
    label,
    person,
    deviceId: track.device_id,
  }));
}

function eventLines(events, allowed) {
  const out = [];
  for (const row of events || []) {
    const person = personById(row.group_id);
    if (!person || !allowed.has(person.id)) continue;
    out.push({
      kind: "event",
      at: Date.parse(row.observed_at),
      iso: row.observed_at,
      id: `e${row.id}`,
      person,
      place: row.place_name,
      arrived: row.event_type === "ENTER",
    });
  }
  return out;
}

/** Every line for the loaded day, newest first. [] when no timeline is loaded. */
export function buildFeed(events) {
  const tracks = state.timeline ? visibleTracks(state.timeline.tracks) : [];
  const allowed = new Set();
  const lines = [];
  for (const track of tracks) {
    const person = personForDevice(track.device_id);
    if (person) allowed.add(person.id);
    lines.push(...sightingLines(track));
  }
  lines.push(...eventLines(events, allowed));
  // Newest first; at a tie a sighting sorts after the event it caused.
  return lines.sort((a, b) => b.at - a.at || (a.kind === "event" ? -1 : 1));
}
