/*
 * "Where was this line?": find the stay, trip or sighting a summary line is about.
 *
 * Purpose    : Selecting "7:40 AM left Home" must move the map and the day story
 *              to that moment. A line carries a time (`at`) and the trackers that
 *              back it (`evidence`); this finds the stay or trip of one of those
 *              trackers that covers the time, else the nearest sighting.
 * Inputs     : A normalised summary line and {payloads, tracks, focusId}.
 * Outputs    : {device, item} (a stay or trip), {device, point: [lat, lon]}, or null.
 * Constraints: Pure: no DOM, no network. A line with no usable time finds nothing,
 *              and the page then leaves the map where it is.
 */
"use strict";

const NEAR_MS = 45 * 60 * 1000;
const lat = (p) => (p.lat !== undefined ? p.lat : p.latitude);
const lon = (p) => (p.lon !== undefined ? p.lon : p.longitude);

/** Trackers to look through: the line's own evidence first, then the one on screen, then the rest. */
function searchOrder(line, ctx) {
  const known = [...ctx.payloads.keys()];
  const own = (line.evidence || []).filter((id) => known.includes(id));
  return [...new Set([...own, ctx.focusId, ...known].filter(Boolean))];
}

function covering(payload, at) {
  const items = [...payload.stays, ...payload.trips];
  return items.find((x) => Date.parse(x.start_at) - 60000 <= at && at <= Date.parse(x.end_at) + 60000) || null;
}

function nearest(line, ctx, at, order) {
  let best = null;
  ctx.tracks.filter((tr) => order.includes(tr.device_id)).forEach((tr) => {
    tr.points.filter((p) => !p.suspect).forEach((p) => {
      const gap = Math.abs(Date.parse(p.observed_at) - at);
      if (gap <= NEAR_MS && (!best || gap < best.gap)) best = { gap, device: tr.device_id, point: [lat(p), lon(p)] };
    });
  });
  return best && { device: best.device, point: best.point };
}

/** The moment a summary line points at, or null. */
export function focusMoment(line, ctx) {
  const at = Date.parse(line.at || "");
  if (Number.isNaN(at)) return null;
  const order = searchOrder(line, ctx);
  for (const device of order) {
    const payload = ctx.payloads.get(device);
    const item = payload && covering(payload, at);
    if (item) return { device, item };
  }
  return nearest(line, ctx, at, order);
}
