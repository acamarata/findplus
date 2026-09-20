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

import { state, colorFor, fmtTime, fmtDateTime, fmtDuration, fmtDistance, esc } from "./state.js";
import { selectPoint } from "./timeline.js";
import { renderBadge } from "./components/badge.js";

export function initMap() {
  state.map = L.map("map", { zoomControl: true }).setView([39.5, -98.35], 4);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(state.map);
  state.layer = L.layerGroup().addTo(state.map);
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
  const ring = index === 0 ? "#37c67a" : index === total - 1 ? "#ef5f5f" : "#fff";
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
      `<div class="${classes.join(" ")}" style="border-color:${ring}">` +
      `<span class="marker-num-glyph">${glyph}</span>` +
      `<span class="marker-num-seq">${point.sequence}</span></div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

function popupHtml(point, deviceName) {
  const rows = [
    `<b>${fmtTime(point.observed_at_local)}</b>`,
    `<div style="opacity:.75">${esc(deviceName)}</div>`,
    `<div>${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}</div>`,
  ];
  if (point.accuracy_meters != null) {
    rows.push(`<div>Accuracy ~${Math.round(point.accuracy_meters)} m</div>`);
  }
  if (point.seconds_since_previous !== null) {
    rows.push(`<div>${fmtDuration(point.seconds_since_previous)} since previous observation</div>`);
  }
  const dist = fmtDistance(point.meters_from_previous);
  if (dist) rows.push(`<div>${dist} from previous observation</div>`);
  if (point.source) rows.push(`<div style="opacity:.7">Report: ${esc(point.source)}</div>`);
  if (!point.is_movement && point.seconds_since_previous !== null) {
    rows.push(`<div style="opacity:.7">Below movement threshold</div>`);
  }
  rows.push(`<div style="opacity:.6;font-size:11px;margin-top:5px">Retrieved ${fmtDateTime(point.fetched_at)}</div>`);
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

  state.timeline.tracks.forEach((track) => {
    const points = visiblePoints(track);
    if (!points.length) return;
    const color = colorFor(track.device_id);
    const device = deviceForTrack(track);
    // D-P2-15: a map marker shows the label as well as the icon and colour.
    // The tooltip, the hover title and the popup are the only text the map
    // has, so they read the label first, exactly as the device list and the
    // timeline track head do.
    const shown = device.label || track.device_name;
    const latlngs = points.map((p) => [p.latitude, p.longitude]);
    allLatLngs.push(...latlngs);

    if (latlngs.length > 1) {
      L.polyline(latlngs, { color, weight: 3, opacity: 0.75, dashArray: "6 5" })
        .addTo(state.layer)
        .bindTooltip(`${esc(shown)} — observed path; actual route between detections may differ.`);
    }

    points.forEach((point, index) => {
      const marker = L.marker([point.latitude, point.longitude], {
        icon: numberedIcon(point, index, points.length, device),
        title: `${shown} · ${fmtTime(point.observed_at_local)}`,
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
