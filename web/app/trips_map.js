/*
 * Day story on the map: trips as arrowed lines, stays as sized markers.
 *
 * Purpose    : Draw one tracker's day the way the story list tells it. Each trip
 *              is a directional polyline in its own colour (dashed while it is
 *              only straight lines between sightings, solid when a road route
 *              came back), each stay one marker sized by how long it lasted and
 *              named after the place, and the sightings inside a stay stay
 *              hidden. A fix dropped as a stray shows faintly.
 * Inputs     : A context built by trips_view.js: the /api/trips body, the road
 *              routes found so far, the selected item id, the tracker's own
 *              fixes (for the sightings inside stays) and a click callback.
 * Outputs    : Layers on state.layer (cleared by renderMap, purged on lock) and
 *              `storyDrawn()` for the map's empty note.
 * Constraints: Leaflet is the global `L`. CSP forbids inline style attributes, so
 *              arrowheads are SVG with a rotate() attribute, not CSS. Nothing on
 *              the map is a Tab stop (keyboard: false); the list is the keyboard path.
 */
"use strict";

import { state, fmtDistance } from "./state.js";
import { t } from "./i18n.js";
import { showSuspect } from "./suspect_pref.js";
import { TRIP_COLORS, STAY_COLOR, clockOf, rangeText, sightingsText, titleOf } from "./trips_format.js";

const MAX_ARROWS = 10;
const MIN_ARROW_METERS = 40;
let drawn = false;

export const storyDrawn = () => drawn;
export const clearStoryDrawn = () => { drawn = false; };

const reduced = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const pad = { padding: [42, 42], maxZoom: 17 };

/** Arrow SVG for the bearing from a to b (0 = north, clockwise). */
function arrowIcon(a, b, color) {
  const dLat = b[0] - a[0];
  const dLon = (b[1] - a[1]) * Math.cos((a[0] * Math.PI) / 180);
  const deg = Math.round((Math.atan2(dLon, dLat) * 180) / Math.PI);
  const svg =
    `<svg viewBox="-8 -8 16 16" width="16" height="16" aria-hidden="true">` +
    `<path d="M0 -6 L5 5 L0 2 L-5 5 Z" fill="${color}" stroke="#fff" stroke-width="1.2" transform="rotate(${deg})"/></svg>`;
  return L.divIcon({ className: "story-arrow", html: svg, iconSize: [16, 16], iconAnchor: [8, 8] });
}

/** Up to MAX_ARROWS arrowheads at segment midpoints, skipping tiny segments. */
function drawArrows(latlngs, color) {
  const segs = [];
  for (let i = 0; i + 1 < latlngs.length; i += 1) {
    if (state.map.distance(latlngs[i], latlngs[i + 1]) >= MIN_ARROW_METERS) segs.push(i);
  }
  const step = Math.max(1, Math.ceil(segs.length / MAX_ARROWS));
  segs.filter((_, k) => k % step === 0).forEach((i) => {
    const [a, b] = [latlngs[i], latlngs[i + 1]];
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    L.marker(mid, { icon: arrowIcon(a, b, color), interactive: false, keyboard: false }).addTo(state.layer);
  });
}

/** The line for a trip: the road route when one came back, else its sightings. */
function tripLine(trip, route) {
  const road = route && route.style === "solid" && route.geometry && route.geometry.type === "LineString";
  const coords = road ? route.geometry.coordinates.map(([lon, lat]) => [lat, lon]) : null;
  if (coords && coords.length >= 2) return { latlngs: coords, solid: true };
  return { latlngs: trip.points.map((p) => [p.latitude, p.longitude]), solid: false };
}

function tripTip(trip, route) {
  const base = t("trips.tripTip", { title: titleOf(trip), range: rangeText(trip), distance: fmtDistance(trip.distance_meters) });
  const missed = route && (route.failed || route.style !== "solid");
  return missed ? `${base} ${t("trips.tripTipFallback")}` : base;
}

/** Draw one trip; returns its latlngs for fitting. */
function drawTrip(ctx, trip) {
  const color = TRIP_COLORS[trip.colorIndex];
  const route = ctx.routes.get(trip.id);
  const { latlngs, solid } = tripLine(trip, route);
  const picked = ctx.selectedId === trip.id;
  L.polyline(latlngs, { color: "#fff", weight: picked ? 9 : 7, opacity: 0.7, interactive: false, keyboard: false }).addTo(state.layer);
  const line = L.polyline(latlngs, {
    color, weight: picked ? 6 : 4, opacity: 0.95, lineJoin: "round", keyboard: false,
    dashArray: solid ? null : "9 8",
  }).addTo(state.layer);
  line.bindTooltip(tripTip(trip, route), { sticky: true });
  line.on("click", () => ctx.onPick(trip.id));
  drawArrows(latlngs, color);
  return latlngs;
}

const stayRadius = (stay) => Math.min(26, 8 + Math.sqrt(stay.duration_minutes) * 0.9);

function stayPopup(stay) {
  const box = document.createElement("div");
  const head = document.createElement("b");
  head.textContent = titleOf(stay);
  const when = document.createElement("div");
  when.textContent = `${rangeText(stay)} · ${sightingsText(stay.fix_count)}`;
  box.append(head, when);
  return box;
}

/** One marker per stay, sized by dwell, with the place name as its label. */
function drawStay(ctx, stay, label) {
  const picked = ctx.selectedId === stay.id;
  const marker = L.circleMarker([stay.latitude, stay.longitude], {
    radius: stayRadius(stay), color: picked ? "#2f6fe6" : "#fff", weight: picked ? 4 : 2,
    fillColor: STAY_COLOR, fillOpacity: 0.85, keyboard: false,
  }).addTo(state.layer);
  marker.bindTooltip(titleOf(stay), { permanent: label, direction: "top", className: "story-label", offset: [0, -4] });
  marker.bindPopup(stayPopup(stay));
  marker.on("click", () => ctx.onPick(stay.id));
  return [stay.latitude, stay.longitude];
}

/** A stray fix: faint, and it says why it is not part of the path. */
function drawStray(fix) {
  if (!showSuspect()) return;
  const at = [fix.latitude, fix.longitude];
  const tip = fix.suspect_reason ? `${clockOf(fix.local)} ${fix.suspect_reason}` : t("trips.strayTip", { time: clockOf(fix.local) });
  L.circleMarker(at, {
    radius: 4, color: "#64748b", weight: 1, opacity: 0.55, fillColor: "#94a3b8", fillOpacity: 0.3, keyboard: false,
  }).addTo(state.layer).bindTooltip(tip);
  L.circleMarker(at, {
    radius: 10, color: "#64748b", weight: 1.5, opacity: 0.6, dashArray: "3 3", fill: false, keyboard: false,
  }).addTo(state.layer).bindTooltip(tip);
}

/** Fixes of the tracker's own list whose time falls in [from, to] (ISO text from either API). */
const within = (fixes, from, to) => {
  const [a, b] = [Date.parse(from), Date.parse(to)];
  return fixes.filter((p) => Date.parse(p.observed_at) >= a && Date.parse(p.observed_at) <= b);
};

const dot = (p, radius, fill) =>
  L.circleMarker([p.latitude, p.longitude], { radius, color: "#fff", weight: 1, fillColor: fill, fillOpacity: 0.9, keyboard: false })
    .bindTooltip(clockOf(p.observed_at_local || p.local));

/** The sightings inside every stay, small, only when the person asked for them. */
function drawInside(ctx) {
  ctx.payload.stays.forEach((s) =>
    within(ctx.fixes, s.start_at, s.end_at).forEach((p) => dot(p, 3, STAY_COLOR).addTo(state.layer))
  );
}

/** Highlight the picked item: its own sightings, and the stay's extent. */
function drawSelection(ctx, item) {
  const group = L.layerGroup().addTo(state.layer);
  if (item.kind === "trip") {
    item.points.forEach((p) => dot({ ...p, observed_at_local: p.local }, 5, "#2f6fe6").addTo(group));
    return L.latLngBounds(item.points.map((p) => [p.latitude, p.longitude]));
  }
  const ring = L.circle([item.latitude, item.longitude], {
    radius: Math.max(item.radius_meters, 30), color: "#2f6fe6", weight: 2, dashArray: "4 4", fillOpacity: 0.06, interactive: false,
  }).addTo(group);
  within(ctx.fixes, item.start_at, item.end_at).forEach((p) => dot(p, 4, "#2f6fe6").addTo(group));
  return ring.getBounds();
}

/** Draw the whole story; returns the bounds of everything, or null. */
export function drawStory(ctx) {
  drawn = true;
  const all = [];
  const labelled = ctx.payload.stays.length <= 8;
  ctx.payload.stays.forEach((s) => all.push(drawStay(ctx, s, labelled && s.place_id != null)));
  ctx.payload.trips.forEach((trip, i) => all.push(...drawTrip(ctx, { ...trip, colorIndex: i % TRIP_COLORS.length })));
  ctx.payload.outliers.forEach(drawStray);
  if (ctx.showInside) drawInside(ctx);
  const picked = [...ctx.payload.stays, ...ctx.payload.trips].find((x) => x.id === ctx.selectedId);
  const focus = picked ? drawSelection(ctx, picked) : null;
  const bounds = all.length ? L.latLngBounds(all) : null;
  return { bounds, focus };
}

/** Move the map to `bounds`, without animation when the person asked for less motion. */
export function frame(bounds) {
  if (bounds && bounds.isValid()) state.map.fitBounds(bounds, { ...pad, animate: !reduced() });
}

/** Lock purge: Leaflet keeps removed layers' tooltip and popup nodes in their panes. */
export function purgeMapPanes() {
  if (!state.map) return;
  ["tooltipPane", "popupPane"].forEach((name) => state.map.getPane(name)?.replaceChildren());
}
