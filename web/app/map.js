/*
 * Leaflet map: markers, numbered icons, popups, and the observed-path lines.
 *
 * Purpose    : Render one INDEPENDENT track per device on the map. Tracks are
 *              never merged — distance/elapsed-time are only meaningful
 *              within a single tracker's own points.
 * Constraints: Leaflet is a global loaded by a CDN <script> tag in
 *              index.html — referenced here as `L` (window.L), never
 *              imported as an ES module.
 */
"use strict";

import { state, colorFor, displayName, visibleTracks, fmtTime, fmtDateTime, fmtDuration, fmtDistance, esc } from "./state.js";
import { selectPoint } from "./timeline.js";
import { renderBadge } from "./components/badge.js";
import { t } from "./i18n.js";
import { api } from "./api.js";

// U4 (R-P2-30.2): a US-centred default read as "my child is in Kansas" the
// first time the map had no data to fit. A neutral world view says nothing
// about anyone's location; setDefaultView() below replaces it with a real
// fit whenever there is data to fit to. lock.js's purge reuses the same pair
// so the lock screen never regresses to the old US default either.
export const WORLD_VIEW_CENTER = [20, 0];
export const WORLD_VIEW_ZOOM = 2;

export function initMap() {
  state.map = L.map("map", { zoomControl: true }).setView(WORLD_VIEW_CENTER, WORLD_VIEW_ZOOM);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(state.map);
  state.layer = L.layerGroup().addTo(state.map);
}

/**
 * The map's starting view, before any day's timeline has been fitted.
 *
 * Order (R-P2-30.2): the tracked devices' latest fixes, else the saved
 * places, else the plain world view -- never a hardcoded country. A day
 * that turns out to have observations still wins in the end: renderMap()'s
 * own fitBounds() runs after this and overrides it, so this is only ever
 * the view a data-less boot (first run, a quiet day, the wizard) is left
 * with.
 */
export async function setDefaultView() {
  if (!state.map) return;
  const points = await _trackedDeviceFixes();
  if (points.length) {
    state.map.fitBounds(L.latLngBounds(points), { padding: [42, 42], maxZoom: 14 });
    return;
  }
  const places = await api("/api/places").catch(() => []);
  if (places.length) {
    state.map.fitBounds(
      L.latLngBounds(places.map((p) => [p.latitude, p.longitude])),
      { padding: [42, 42], maxZoom: 14 },
    );
    return;
  }
  state.map.setView(WORLD_VIEW_CENTER, WORLD_VIEW_ZOOM);
}

/** One [lat, lon] per tracked device that has ever reported, skipping any
 * that have not (a 404 from /api/latest) rather than failing the whole
 * default-view computation over one silent tracker. */
async function _trackedDeviceFixes() {
  const devicesResp = await api("/api/devices").catch(() => null);
  const tracked = devicesResp ? devicesResp.devices.filter((d) => d.is_tracked) : [];
  const fixes = await Promise.all(
    tracked.map((d) =>
      api(`/api/latest?device_id=${encodeURIComponent(d.device_id)}`).catch(() => null),
    ),
  );
  return fixes.filter(Boolean).map((f) => [f.latitude, f.longitude]);
}

/**
 * The numbered marker for one point, in its device's colour and icon.
 *
 * The number is the point's order within its track, not its identity, so it
 * stays; the flat background behind it becomes the device's badge. `device` is
 * resolved by the caller, which keeps this function free of any state lookup.
 *
 * This is the one place in the app that reads a badge as markup:
 * `L.divIcon({ html })` takes a string, not a node (specs/labels-and-icons.md
 * § Rendering). Every other caller appends the live SVGElement.
 */
function numberedIcon(point, index, total, device) {
  const classes = ["marker-num"];
  if (!point.is_movement) classes.push("jitter");
  // The ring colour used to be a per-marker inline style="border-color:…",
  // which CSP's default `style-src 'self'` (no unsafe-inline) silently drops
  // -- every marker rendered with a plain white ring and the console filled
  // with CSP violation warnings (UAT U25). first/last are the only two
  // non-default rings; components.css owns the actual colours.
  if (index === 0) classes.push("marker-num--first");
  else if (index === total - 1) classes.push("marker-num--last");
  const glyph = point.is_movement
    ? renderBadge({
        icon: device.icon,
        color: device.color,
        label: device.label,
        name: device.name,
        size: 26,
      }).outerHTML
    : "";
  return L.divIcon({
    className: "",
    html:
      `<div class="${classes.join(" ")}">` +
      `<span class="marker-num-glyph">${glyph}</span>` +
      `<span class="marker-num-seq">${point.sequence}</span></div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

function popupHtml(point, deviceName) {
  // UAT2 N14: the tracker's name is the heading, not a subtitle under the
  // time -- a popup with several tracks open at once otherwise reads as a
  // bare timestamp with no way to tell whose fix it is.
  const rows = [
    `<b>${esc(deviceName)}</b>`,
    `<div class="fp-popup-sub">${fmtTime(point.observed_at_local)}</div>`,
    `<div>${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}</div>`,
  ];
  if (point.accuracy_meters != null) {
    rows.push(`<div>Accuracy ~${Math.round(point.accuracy_meters)} m</div>`);
  } else {
    // Apple Find My never reports a metres figure (CF-P2-6): say so plainly
    // instead of just omitting the line, which could read as "exact".
    rows.push(`<div>${esc(t("timeline.accuracyUnknown"))}</div>`);
  }
  if (point.seconds_since_previous !== null) {
    rows.push(`<div>${fmtDuration(point.seconds_since_previous)} since previous observation</div>`);
  }
  const dist = fmtDistance(point.meters_from_previous);
  if (dist) rows.push(`<div>${dist} from previous observation</div>`);
  if (point.source) rows.push(`<div class="fp-popup-meta">Report: ${esc(point.source)}</div>`);
  if (!point.is_movement && point.seconds_since_previous !== null) {
    rows.push(`<div class="fp-popup-meta">Below movement threshold</div>`);
  }
  rows.push(`<div class="fp-popup-retrieved">Retrieved ${fmtDateTime(point.fetched_at)}</div>`);
  return rows.join("");
}

/**
 * The device a track belongs to, or a stand-in that still renders.
 *
 * A track can outlive its device row (a tracker removed after its observations
 * were ingested), and timeline.js needs the same answer this file does, so the
 * fallback lives here once rather than as two copies that can drift.
 * `state.devices` holds tens of rows, so a linear scan is the right shape.
 */
export function deviceForTrack(track) {
  return (
    state.devices.find((d) => d.device_id === track.device_id) || {
      icon: "none",
      color: colorFor(track.device_id),
      label: null,
      name: track.device_name,
    }
  );
}

export function visiblePoints(track) {
  return state.movementOnly ? track.points.filter((p) => p.is_movement) : track.points;
}

export function renderMap() {
  state.layer.clearLayers();
  state.markers.clear();
  if (!state.timeline) return;

  const allLatLngs = [];

  // The dashboard's group select narrows both the map and the timeline to
  // one group's members client-side, with no second fetch (UAT U8).
  visibleTracks(state.timeline.tracks).forEach((track) => {
    const points = visiblePoints(track);
    if (!points.length) return;
    const color = colorFor(track.device_id);
    const device = deviceForTrack(track);
    // D-P2-15: a map marker shows the label as well as the icon and colour.
    // The tooltip, the hover title and the popup are the only text the map
    // has, so they read the label first, exactly as the device list and the
    // timeline track head do (UAT U6: the one displayName() helper).
    const shown = displayName(device) || track.device_name;
    const latlngs = points.map((p) => [p.latitude, p.longitude]);
    allLatLngs.push(...latlngs);

    if (latlngs.length > 1) {
      // keyboard: false (U31) — Leaflet's default Tab-stop-per-path/marker
      // behaviour put every point of every track in the Tab order ahead of
      // the timeline; a keyboard user reaches the timeline directly and picks
      // a point from there instead (selectPoint() below draws its marker).
      L.polyline(latlngs, { color, weight: 3, opacity: 0.75, dashArray: "6 5", keyboard: false })
        .addTo(state.layer)
        .bindTooltip(`${esc(shown)} — observed path; actual route between detections may differ.`);
    }

    points.forEach((point, index) => {
      const marker = L.marker([point.latitude, point.longitude], {
        icon: numberedIcon(point, index, points.length, device),
        title: `${shown} · ${fmtTime(point.observed_at_local)}`,
        keyboard: false,
      }).addTo(state.layer);
      marker.bindPopup(popupHtml(point, shown));
      marker.on("click", () => selectPoint(point.id, false));
      state.markers.set(point.id, marker);
    });
  });

  if (allLatLngs.length) {
    state.map.fitBounds(L.latLngBounds(allLatLngs), { padding: [42, 42], maxZoom: 17 });
  }
}
