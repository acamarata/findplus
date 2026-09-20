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

export function initMap() {
  state.map = L.map("map", { zoomControl: true }).setView([39.5, -98.35], 4);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(state.map);
  state.layer = L.layerGroup().addTo(state.map);
}

function numberedIcon(point, index, total, color) {
  const classes = ["marker-num"];
  if (!point.is_movement) classes.push("jitter");
  const bg = point.is_movement ? color : "#6b7688";
  const ring = index === 0 ? "#37c67a" : index === total - 1 ? "#ef5f5f" : "#fff";
  return L.divIcon({
    className: "",
    html: `<div class="${classes.join(" ")}" style="background:${bg};border-color:${ring}">${point.sequence}</div>`,
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
    const latlngs = points.map((p) => [p.latitude, p.longitude]);
    allLatLngs.push(...latlngs);

    if (latlngs.length > 1) {
      L.polyline(latlngs, { color, weight: 3, opacity: 0.75, dashArray: "6 5" })
        .addTo(state.layer)
        .bindTooltip(`${esc(track.device_name)} — observed path; actual route between detections may differ.`);
    }

    points.forEach((point, index) => {
      const marker = L.marker([point.latitude, point.longitude], {
        icon: numberedIcon(point, index, points.length, color),
        title: `${track.device_name} · ${fmtTime(point.observed_at_local)}`,
      }).addTo(state.layer);
      marker.bindPopup(popupHtml(point, track.device_name));
      marker.on("click", () => selectPoint(point.id, false));
      state.markers.set(point.id, marker);
    });
  });

  if (allLatLngs.length) {
    state.map.fitBounds(L.latLngBounds(allLatLngs), { padding: [42, 42], maxZoom: 17 });
  }
}
