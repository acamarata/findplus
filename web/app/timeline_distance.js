/*
 * "N mi from the previous sighting", measured from the previous TRUSTED fix.
 *
 * Purpose    : The API measures each row from the sighting just before it. When
 *              that one was flagged as wrong (a jump far away and back), the row
 *              after it read "1.49 mi from previous" although it sits where the
 *              tracker already was. A flagged fix is not a place the tracker
 *              was, so the distance is taken from the last fix that was trusted.
 * Inputs     : A track's points (oldest first) and one point of it.
 * Outputs    : Metres, or null when there is no earlier trusted fix.
 * Constraints: Pure. An untouched row keeps the API's own number.
 */
"use strict";

const EARTH_M = 6371008.8;
const rad = (deg) => (deg * Math.PI) / 180;

function haversine(a, b) {
  const dLat = rad(b.latitude - a.latitude);
  const dLon = rad(b.longitude - a.longitude);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.latitude)) * Math.cos(rad(b.latitude)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Metres from the previous trusted sighting to `point`. */
export function metersFromTrusted(points, point) {
  const at = points.indexOf(point);
  if (at <= 0) return point.meters_from_previous;
  if (!points[at - 1].suspect) return point.meters_from_previous;
  for (let i = at - 2; i >= 0; i -= 1) {
    if (!points[i].suspect) return haversine(points[i], point);
  }
  return null;
}
