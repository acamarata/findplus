/*
 * The Person page's map layers: one line per tracker, stays, and faint
 * "looks wrong" sightings.
 *
 * Purpose    : Draw a person's day on the shared dashboard map without ever
 *              merging trackers: each tracker gets its own polyline in its own
 *              colour, its own stays (sized by how long it stayed) and its own
 *              suspect sightings. A suspect fix is a faint dot inside a dashed
 *              ring, with the plain-words reason as its tooltip.
 * Inputs     : A context {tracks, trips, leadId, showSuspect, colorOf, nameOf,
 *              onPickStay} built by person_page.js.
 * Outputs    : Layers on the layer group it is given; returns {bounds}.
 *              frameBounds(), flashPoint() and highlight() move and mark the map.
 * Constraints: Leaflet is the global `L`. Nothing on the map is a Tab stop
 *              (keyboard: false); the summary and the day story are the
 *              keyboard path. CSP forbids inline styles: presentation goes in
 *              Leaflet options. Suspect fixes never join a line.
 */
"use strict";

import { state, esc } from "./state.js";
import { t } from "./i18n.js";
import { clockOf, rangeText, titleOf } from "./trips_format.js";

const reduced = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const lat = (p) => (p.lat !== undefined ? p.lat : p.latitude);
const lon = (p) => (p.lon !== undefined ? p.lon : p.longitude);
const stayRadius = (stay) => Math.min(24, 7 + Math.sqrt(stay.duration_minutes) * 0.85);

/** One tracker's line through its trusted sightings, plus a dot at its newest one. */
function drawLine(layer, track, ctx) {
  const color = ctx.colorOf(track.device_id);
  const lead = track.device_id === ctx.leadId;
  const good = track.points.filter((p) => !p.suspect);
  const latlngs = good.map((p) => [lat(p), lon(p)]);
  const name = ctx.nameOf(track.device_id);
  if (latlngs.length > 1) {
    L.polyline(latlngs, { color, weight: lead ? 4 : 3, opacity: lead ? 0.9 : 0.7, dashArray: "6 5", keyboard: false })
      .addTo(layer).bindTooltip(esc(name), { sticky: true });
  }
  if (good.length) {
    const last = good[good.length - 1];
    L.circleMarker([lat(last), lon(last)], {
      radius: lead ? 7 : 5, color: "#fff", weight: 2, fillColor: color, fillOpacity: 0.95, keyboard: false,
    }).addTo(layer).bindTooltip(esc(`${name} ${clockOf(last.observed_at_local || "")}`.trim()));
  }
  return latlngs;
}

/** A sighting that looks wrong: faint, ringed with a dashed line, with its reason on hover. */
function drawSuspect(layer, point, name) {
  const at = [lat(point), lon(point)];
  const reason = point.suspect_reason || t("person.map.suspectTip");
  const tip = esc(`${name}: ${reason}`);
  L.circleMarker(at, {
    radius: 4, color: "#64748b", weight: 1, opacity: 0.55, fillColor: "#94a3b8", fillOpacity: 0.3, keyboard: false,
  }).addTo(layer).bindTooltip(tip);
  L.circleMarker(at, {
    radius: 10, color: "#64748b", weight: 1.5, opacity: 0.6, dashArray: "3 3", fill: false, keyboard: false,
  }).addTo(layer).bindTooltip(tip);
}

function stayTip(stay, name) {
  return `${name}: ${t("person.map.stay", { place: titleOf(stay), range: rangeText(stay) })}`;
}

/** The tracker's stays, sized by dwell, ringed in the tracker's colour. */
function drawStays(layer, device, payload, ctx) {
  const color = ctx.colorOf(device);
  const name = ctx.nameOf(device);
  const lead = device === ctx.leadId;
  return payload.stays.map((stay) => {
    const marker = L.circleMarker([stay.latitude, stay.longitude], {
      radius: stayRadius(stay), color, weight: lead ? 3 : 2, fillColor: color, fillOpacity: lead ? 0.35 : 0.18, keyboard: false,
    }).addTo(layer);
    marker.bindTooltip(esc(stayTip(stay, name)), { direction: "top", offset: [0, -4] });
    marker.on("click", () => ctx.onPickStay(device, stay.id));
    return [stay.latitude, stay.longitude];
  });
}

/** Draw the whole day into `layer`. Returns {bounds} (null when there is nothing to frame). */
export function drawPerson(layer, ctx) {
  layer.clearLayers();
  const all = [];
  ctx.tracks.forEach((track) => {
    all.push(...drawLine(layer, track, ctx));
    if (ctx.showSuspect) {
      track.points.filter((p) => p.suspect).forEach((p) => drawSuspect(layer, p, ctx.nameOf(track.device_id)));
    }
  });
  ctx.trips.forEach((payload, device) => all.push(...drawStays(layer, device, payload, ctx)));
  return { bounds: all.length ? L.latLngBounds(all) : null };
}

const phone = () => window.matchMedia && window.matchMedia("(max-width: 600px)").matches;
const behavior = () => (reduced() ? "auto" : "smooth");

/** On a phone the map and the page stack: bring the map into view after a focus. */
export function showMapOnPhone() {
  if (phone()) document.querySelector(".map-pane")?.scrollIntoView({ block: "nearest", behavior: behavior() });
}

/** On a phone the page sits under the map: bring its header to the top when it opens. */
export function showPageOnPhone() {
  if (phone()) document.getElementById("person-page")?.scrollIntoView({ block: "start", behavior: behavior() });
}

/** Move the map to `bounds`; no animation when the person asked for less motion. */
export function frameBounds(bounds) {
  if (bounds && bounds.isValid && bounds.isValid()) {
    state.map.fitBounds(bounds, { padding: [42, 42], maxZoom: 17, animate: !reduced() });
  }
}

/** Mark one moment: a ring at [lat, lon] that replaces any earlier mark in `layer`. */
export function highlight(layer, at, radiusMeters = 40) {
  layer.clearLayers();
  if (!at) return;
  L.circle(at, { radius: Math.max(radiusMeters, 30), color: "#2f6fe6", weight: 2, dashArray: "4 4", fillOpacity: 0.08, interactive: false })
    .addTo(layer);
}
