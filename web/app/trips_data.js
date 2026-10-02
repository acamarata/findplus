/*
 * Day story data: trips per tracker and day, and the optional road routes.
 *
 * Purpose    : Fetch /api/trips and /api/trips/route once per question and
 *              remember the answers, so redraws (a theme flip, a selection, a
 *              refresh with nothing new) never ask again.
 * Inputs     : A device id, a local day and a signature of that tracker's
 *              fixes (so a refresh that brought a new fix asks again).
 * Outputs    : loadTrips(), cachedTrips(), routingOn(), loadRoute(), routeOf().
 * Constraints: Local API only; a road route is requested only when the routing
 *              server setting is on and the person ticked "Draw likely roads".
 *              Nothing here survives a lock: purgeTripsData() empties it all
 *              and bumps `epoch`, so an answer still in flight is dropped.
 */
"use strict";

import { api } from "./api.js";

const CACHE_MAX = 24;
const cache = new Map();
const routes = new Map();
const inflight = new Map();
let epoch = 0;
let routing = null;

const keyOf = (device, day, sig) => `${device}|${day}|${sig}`;

export function cachedTrips(device, day, sig) {
  return cache.get(keyOf(device, day, sig)) || null;
}

/** The trips body for this tracker and day; asks the server once per signature. */
export function loadTrips(device, day, sig) {
  const key = keyOf(device, day, sig);
  if (cache.has(key)) return Promise.resolve(cache.get(key));
  if (inflight.has(key)) return inflight.get(key);
  const mine = epoch;
  const query = new URLSearchParams({ device_id: device, date: day });
  const job = api(`/api/trips?${query}`)
    .then((body) => {
      if (mine !== epoch) throw Object.assign(new Error("Locked"), { status: 401 });
      remember(device, day, key, body);
      return body;
    })
    .finally(() => inflight.delete(key));
  inflight.set(key, job);
  return job;
}

/** Keep the newest answer per device and day, and at most CACHE_MAX in all. */
function remember(device, day, key, body) {
  for (const old of [...cache.keys()]) if (old.startsWith(`${device}|${day}|`)) cache.delete(old);
  cache.set(key, body);
  routing = Boolean(body.routing_enabled);
  while (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value);
}

/** True/false once known, null before the first answer. */
export const routingOn = () => routing;

/** Read the routing server setting (also learned from every trips answer). */
export async function refreshRouting() {
  const mine = epoch;
  try {
    const body = await api("/api/settings/routing.endpoint");
    if (mine === epoch) routing = Boolean(body && body["routing.endpoint"]);
  } catch (_) {
    /* offline or locked: leave the last known answer */
  }
  return routing;
}

const routeKey = (device, day, id) => `${device}|${day}|${id}`;
export const routeOf = (device, day, id) => routes.get(routeKey(device, day, id)) || null;

/** One trip's likely road route. A failure is remembered as {failed: true}, not retried. */
export async function loadRoute(device, day, id) {
  const key = routeKey(device, day, id);
  if (routes.has(key)) return routes.get(key);
  const mine = epoch;
  const query = new URLSearchParams({ device_id: device, trip_id: id, date: day });
  let result;
  try {
    result = await api(`/api/trips/route?${query}`);
  } catch (err) {
    if (err.status === 401) return null;
    result = { failed: true };
  }
  if (mine !== epoch) return null;
  routes.set(key, result);
  return result;
}

/** Forget routes (the "Draw likely roads" box was switched off or on again). */
export function resetRoutes() {
  routes.clear();
}

/** Lock purge: nothing about where anyone was may stay in memory. */
export function purgeTripsData() {
  epoch += 1;
  cache.clear();
  routes.clear();
  inflight.clear();
  routing = null;
}
