/*
 * One pin for trackers that sit in the same spot.
 *
 * Purpose    : A first-run map with 16 trackers at one address drew 16 pins on top
 *              of each other. Pins within about 35 m now share one numbered pin.
 * Inputs     : [{device, fix}] pairs (map.js's latest-fix list).
 * Outputs    : groupNearby() -> [{lat, lon, items}]; countIcon(n) -> a Leaflet divIcon.
 * Constraints: Pure grouping on a coarse grid; the group's position is the mean of its
 *              fixes. The caller draws a single device's own badge for a group of one.
 */
"use strict";

const CELL_DEG = 0.0003;

export function groupNearby(entries) {
  const cells = new Map();
  entries.forEach((entry) => {
    const key = `${Math.round(entry.fix.latitude / CELL_DEG)},${Math.round(entry.fix.longitude / CELL_DEG)}`;
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key).push(entry);
  });
  return [...cells.values()].map((items) => ({
    items,
    lat: items.reduce((sum, e) => sum + e.fix.latitude, 0) / items.length,
    lon: items.reduce((sum, e) => sum + e.fix.longitude, 0) / items.length,
  }));
}

/** A round pin with the number of trackers in it. */
export function countIcon(count) {
  return L.divIcon({
    className: "",
    html: `<div class="marker-num marker-count"><span class="marker-num-glyph">${count}</span></div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}
