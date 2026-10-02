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

import { uniqueLabel } from "./device_label.js";
import { state, colorFor, displayName, visibleTracks, fmtTime, esc } from "./state.js";
import { selectPoint } from "./timeline.js";
import { renderBadge } from "./components/badge.js";
import { t } from "./i18n.js";
import { api } from "./api.js";
import { syncMapOverlay } from "./map_empty.js";
import { renderLegend, syncDense, watchTiles } from "./map_extras.js";
import { popupHtml } from "./map_popup.js";
import { storyMapRender } from "./trips_view.js";
import { showSuspect } from "./suspect_pref.js";
import { countIcon, groupNearby } from "./map_pins.js";

// U4 (R-P2-30.2): a US-centred default read as "my child is in Kansas" the
// first time the map had no data to fit. A neutral world view says nothing
// about anyone's location; setDefaultView() below replaces it with a real
// fit whenever there is data to fit to. lock.js's purge reuses the same pair
// so the lock screen never regresses to the old US default either.
export const WORLD_VIEW_CENTER = [20, 0];
export const WORLD_VIEW_ZOOM = 2;

/** The inhabited world, trimmed of the polar bands. */
const WORLD_BOUNDS = [[-58, -170], [78, 175]];

/** Fit the whole world into the map's own box, whatever size it is. A fixed
 * zoom 2 left a wide, short box showing the same continents twice. */
function fitWorld() {
  state.map.fitBounds(WORLD_BOUNDS, { animate: false });
}

export function initMap() {
  state.map = L.map("map", { zoomControl: true }).setView(WORLD_VIEW_CENTER, WORLD_VIEW_ZOOM);
  const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(state.map);
  watchTiles(tiles, document.querySelector(".map-pane"));
  state.map.getContainer().setAttribute("aria-label", t("map.label"));
  state.map.on("zoomend", () => syncDense(state.map, state.markers.size));
  state.layer = L.layerGroup().addTo(state.map);
  // Leaflet only measures its container once. If the pane was hidden, still
  // laying out, or later resized (window drag, tab switch, banner appearing),
  // tiles render into a stale tiny box. Re-measure whenever the box changes.
  const el = document.getElementById("map");
  if (el && typeof ResizeObserver === "function") {
    new ResizeObserver(() => state.map && state.map.invalidateSize()).observe(el);
  }
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
  fitWorld();
}

/** Each tracked device paired with its latest fix, skipping any that have
 * none yet rather than failing over one silent tracker. A device with zero
 * observations is not asked at all: its /api/latest is a guaranteed 404,
 * which the browser logged as a console error on every boot (UAT6-N35).
 * The one fetch both setDefaultView() and renderTrackedDeviceMarkers() build
 * on, so a first-run wizard borrowing this map never issues it twice. */
async function _trackedDeviceLatest() {
  const devicesResp = await api("/api/devices").catch(() => null);
  const tracked = devicesResp
    ? devicesResp.devices.filter((d) => d.is_tracked && Number(d.observation_count) > 0)
    : [];
  const fixes = await Promise.all(
    tracked.map((d) =>
      api(`/api/latest?device_id=${encodeURIComponent(d.device_id)}`).catch(() => null),
    ),
  );
  return tracked.map((device, i) => ({ device, fix: fixes[i] })).filter((entry) => entry.fix);
}

/** One [lat, lon] per tracked device that has ever reported. */
async function _trackedDeviceFixes() {
  return (await _trackedDeviceLatest()).map(({ fix }) => [fix.latitude, fix.longitude]);
}

/**
 * True-first-run fallback for the wizard's Places step (UAT4 N36): draw one
 * marker per tracked device's latest fix, with no track line and no numbered
 * sequence, since there is no timeline loaded yet to draw one from -- a never-
 * booted dashboard never populates state.timeline, so the borrowed map used
 * to show only the place circles places.js (the tab module) draws on its own
 * layer. A no-op once the dashboard HAS booted (state.timeline set):
 * renderMap() already drew the real tracks by then, on the wizard's re-run
 * path, and this must never overwrite them. The wizard's Places step passes
 * `force`: one pin per spot (trackers that sit together share one numbered
 * pin) reads better there than every sighting of every tracker; it calls
 * renderMap() on the way out to put the real tracks back.
 */
export async function renderTrackedDeviceMarkers({ force = false } = {}) {
  if (!state.map || (state.timeline && !force)) return;
  state.layer.clearLayers();
  const entries = await _trackedDeviceLatest();
  groupNearby(entries).forEach((group) => {
    if (group.items.length > 1) {
      const names = group.items.map(({ device }) => displayName(device) || device.name).join(", ");
      L.marker([group.lat, group.lon], { icon: countIcon(group.items.length), title: names, keyboard: false }).addTo(state.layer);
      return;
    }
    const { device, fix } = group.items[0];
    const shown = displayName(device) || device.name;
    const icon = L.divIcon({
      className: "",
      html:
        `<div class="marker-num"><span class="marker-num-glyph">${
          renderBadge({ icon: device.icon, color: device.color, label: device.label, name: device.name, size: 26 }).outerHTML
        }</span></div>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13],
    });
    L.marker([fix.latitude, fix.longitude], { icon, title: shown, keyboard: false }).addTo(state.layer);
  });
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
  if (point.suspect) classes.push("marker-num--suspect");
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
  const shown = showSuspect() ? track.points : track.points.filter((p) => !p.suspect);
  return state.movementOnly ? shown.filter((p) => p.is_movement) : shown;
}

/**
 * Draw one tracker's path and numbered markers; returns its legend entry, or
 * null when it has nothing to show (a movement-only day with no movement).
 */
function drawTrack(track) {
  const points = visiblePoints(track);
  if (!points.length) return null;
  const device = deviceForTrack(track);
  // The path takes the tracker's own colour, the same one its markers and
  // timeline badge use, so the map and the legend agree.
  const color = device.color || colorFor(track.device_id);
  // D-P2-15: a map marker shows the label as well as the icon and colour.
  // The tooltip, the hover title and the popup are the only text the map
  // has, so they read the label first, exactly as the device list and the
  // timeline track head do (UAT U6: the one displayName() helper).
  const shown = uniqueLabel(device) || track.device_name;
  // A sighting that looks wrong never joins the path; it is drawn faintly (see numberedIcon).
  const latlngs = points.filter((p) => !p.suspect).map((p) => [p.latitude, p.longitude]);
  if (latlngs.length > 1) {
    // keyboard: false (U31): Leaflet's default Tab-stop-per-path/marker
    // behaviour put every point of every track in the Tab order ahead of the
    // timeline; a keyboard user picks a point from the timeline instead.
    L.polyline(latlngs, { color, weight: 3, opacity: 0.75, dashArray: "6 5", keyboard: false })
      .addTo(state.layer)
      .bindTooltip(`${esc(shown)}: observed path; actual route between detections may differ.`);
  }
  points.forEach((point, index) => {
    const marker = L.marker([point.latitude, point.longitude], {
      icon: numberedIcon(point, index, points.length, device),
      title: `${shown} · ${fmtTime(point.observed_at_local)}${point.suspect ? ` · ${point.suspect_reason}` : ""}`,
      keyboard: false,
    }).addTo(state.layer);
    marker.bindPopup(popupHtml(point, shown));
    marker.on("click", () => selectPoint(point.id, false));
    state.markers.set(point.id, marker);
  });
  return { name: shown, color, latlngs };
}

export function renderMap({ fit = true } = {}) {
  // The Person page owns the map while it is open (person_route.js).
  if (state.personView) return;
  state.layer.clearLayers();
  state.markers.clear();
  if (!state.timeline) {
    if (state.legend) { state.legend.remove(); state.legend = null; }
    syncMapOverlay();
    return;
  }
  // The day story (trips_view.js) draws its own layers when it is the view on screen.
  if (storyMapRender({ fit })) { syncMapOverlay(); return; }

  const allLatLngs = [];
  const legend = [];

  // The dashboard's group select narrows both the map and the timeline to
  // one group's members client-side, with no second fetch (UAT U8).
  visibleTracks(state.timeline.tracks).forEach((track) => {
    const drawn = drawTrack(track);
    if (!drawn) return;
    allLatLngs.push(...drawn.latlngs);
    legend.push(drawn);
  });

  state.legend = renderLegend(state.map, legend, state.legend);
  syncDense(state.map, state.markers.size);
  if (allLatLngs.length && fit) {
    state.map.fitBounds(L.latLngBounds(allLatLngs), { padding: [42, 42], maxZoom: 17 });
  }
  syncMapOverlay();
}
