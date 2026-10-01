/*
 * Device names that stay distinguishable when two trackers share one.
 *
 * Purpose    : Two trackers can carry the same label or provider name ("Ali Pixel
 *              8a" twice) and looked identical in every picker (UAT #7). One
 *              helper appends a short id tail, only when the name clashes, so
 *              every surface prints the same text for the same tracker.
 * Inputs     : A device row (/api/devices) and the pool of devices it is shown
 *              among: by default the visible ones (tracked, or with history).
 * Outputs    : uniqueLabel(device, pool) -> "Name" or "Name (tail)";
 *              labelMap(pool) -> Map(device_id -> text).
 * Constraints: The tail is the shortest id suffix, at least 4 characters, that
 *              separates the clashing devices: the same rule as the server's
 *              findplus/device_labels.py, which writes the notes, file names
 *              and KML names. A name that is unique is returned unchanged.
 */
"use strict";

import { state, displayName } from "./state.js";

const MIN_TAIL = 4;

/** The visible devices: tracked, or with at least one observation. */
export function visibleDevices(devices = state.devices) {
  return (devices || []).filter((d) => d.is_tracked || d.observation_count > 0);
}

/** The shortest suffix (>= 4 chars) that is unique among `ids`. */
function tailsFor(ids) {
  const longest = Math.max(MIN_TAIL, ...ids.map((i) => i.length));
  for (let size = MIN_TAIL; size <= longest; size++) {
    const tails = new Map(ids.map((i) => [i, i.slice(-size)]));
    if (new Set(tails.values()).size === ids.length) return tails;
  }
  return new Map(ids.map((i) => [i, i]));
}

/** device_id -> label for every device in `pool`, tails only where names clash. */
export function labelMap(pool) {
  const byName = new Map();
  (pool || []).forEach((d) => {
    const key = displayName(d);
    byName.set(key, [...(byName.get(key) || []), d.device_id]);
  });
  const labels = new Map();
  byName.forEach((ids, name) => {
    const tails = ids.length > 1 ? tailsFor([...ids].sort()) : null;
    ids.forEach((id) => labels.set(id, tails ? `${name} (${tails.get(id)})` : name));
  });
  return labels;
}

/** Just the " (tail)" part of `device`'s label in `labels`, or "" when its name is unique. */
export function tailOf(device, labels) {
  return (labels.get(device.device_id) || "").slice((displayName(device) || "").length);
}

/** `device`'s label among `pool`; a device outside the pool is counted in. */
export function uniqueLabel(device, pool = visibleDevices()) {
  if (!device) return null;
  if (!device.device_id) return displayName(device);
  const among = pool.some((d) => d.device_id === device.device_id) ? pool : [...pool, device];
  return labelMap(among).get(device.device_id);
}
