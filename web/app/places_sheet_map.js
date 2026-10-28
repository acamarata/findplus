/*
 * Place sheet: the live preview drawn on the real dashboard map.
 *
 * Purpose    : While the place sheet is open, the map stays visible and shows
 *              the place as it will be saved: a draggable centre marker, the
 *              radius circle in the place's own colour, and a grip on the
 *              circle's east edge. Moving the marker, resizing the circle or
 *              clicking the map (pick mode) tells the sheet; the sheet moves
 *              or resizes it back through `setCentre()` / `setRadius()`.
 *              Replaces the old modal "Pick on map" crosshair mode (U5).
 * Inputs     : The shared Leaflet `map`; `onMove(latlng)` and `onRadius(m)`.
 * Outputs    : Leaflet layers on `map`; `remove()` takes every one away again
 *              (purgeDialog() on lock: coordinates must not linger).
 * Constraints: DOM only through createElement/setAttribute. Pick mode is
 *              one-shot: the next map click moves the centre and ends it.
 */
"use strict";

import { t } from "./i18n.js";

const NUDGE_DEGREES = 0.0002; // about 22 m of latitude per arrow key
const EARTH_RADIUS_M = 6378137;
const HANDLE_BEARING = 90; // due east
const MIN_RADIUS_M = 50;
const MAX_RADIUS_M = 5000;

/** Great-circle point `meters` from `latlng` along `bearingDeg` (0 = north). */
export function destinationPoint(latlng, meters, bearingDeg) {
  const b = (bearingDeg * Math.PI) / 180;
  const lat1 = (latlng.lat * Math.PI) / 180;
  const lng1 = (latlng.lng * Math.PI) / 180;
  const d = meters / EARTH_RADIUS_M;
  const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(b));
  const lng2 =
    lng1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(lat1), Math.cos(d) - Math.sin(lat1) * Math.sin(lat2));
  return L.latLng((lat2 * 180) / Math.PI, (lng2 * 180) / Math.PI);
}

/** Arrow keys nudge the centre marker, so the place can be placed with no pointer. */
function wireKeyboard(marker, nudge) {
  const el = marker.getElement();
  if (!el) return;
  el.classList.add("fp-map-pick-marker");
  el.tabIndex = 0;
  el.setAttribute("role", "button");
  el.setAttribute("aria-label", t("places.mapPick.markerLabel"));
  const deltas = {
    ArrowUp: [NUDGE_DEGREES, 0],
    ArrowDown: [-NUDGE_DEGREES, 0],
    ArrowLeft: [0, -NUDGE_DEGREES],
    ArrowRight: [0, NUDGE_DEGREES],
  };
  el.addEventListener("keydown", (e) => {
    if (!deltas[e.key]) return;
    e.preventDefault();
    nudge(deltas[e.key]);
  });
}

/** One-shot "pick on map": the next map click is handed to `onPoint` and ends the mode. */
function createPicker(map, onPoint) {
  let picking = false;
  function onClick(e) {
    stop();
    onPoint(e.latlng);
  }
  function stop() {
    picking = false;
    map.getContainer().classList.remove("fp-picking");
    map.off("click", onClick);
  }
  function start() {
    picking = true;
    map.getContainer().classList.add("fp-picking");
    map.on("click", onClick);
  }
  return { start, stop, isPicking: () => picking };
}

/** The three layers: the radius circle, the draggable centre pin and the east-edge grip. */
function buildLayers(map, { latlng, radiusMeters, color }) {
  const at = L.latLng(latlng.lat, latlng.lng);
  const circle = L.circle(at, { radius: radiusMeters, color, weight: 2, fillOpacity: 0.14, keyboard: false, interactive: false }).addTo(map);
  const marker = L.marker(at, { draggable: true, keyboard: false }).addTo(map);
  const icon = L.divIcon({ className: "fp-map-pick-radius-handle", iconSize: [14, 14] });
  const handle = L.marker(destinationPoint(at, radiusMeters, HANDLE_BEARING), { draggable: true, keyboard: false, icon }).addTo(map);
  return { circle, marker, handle };
}

/** Drag the pin to move, drag the grip to resize, arrow keys nudge the pin. */
function wireDrag(map, { marker, handle, circle }, { moveTo, placeHandle, onRadius, setRadiusState }) {
  marker.on("drag", () => moveTo(marker.getLatLng()));
  handle.on("drag", () => {
    const measured = Math.round(map.distance(marker.getLatLng(), handle.getLatLng()));
    const metres = Math.min(MAX_RADIUS_M, Math.max(MIN_RADIUS_M, measured));
    setRadiusState(metres);
    circle.setRadius(metres);
    onRadius(metres);
  });
  handle.on("dragend", placeHandle);
  wireKeyboard(marker, ([dLat, dLng]) => {
    const at = marker.getLatLng();
    moveTo({ lat: at.lat + dLat, lng: at.lng + dLng });
  });
}

/**
 * Build the preview controller. Nothing is on the map until `show()` is called;
 * `remove()` takes every layer (and pick mode) away again.
 */
export function createSheetPreview(map, { onMove, onRadius }) {
  let layers = null;
  let radius = 100;
  const placeHandle = () => layers.handle.setLatLng(destinationPoint(layers.marker.getLatLng(), radius, HANDLE_BEARING));

  function moveTo(next, notify = true) {
    layers.marker.setLatLng(next);
    layers.circle.setLatLng(next);
    placeHandle();
    if (notify) onMove({ lat: next.lat, lng: next.lng });
  }

  const picker = createPicker(map, (latlng) => moveTo(latlng));

  function remove() {
    picker.stop();
    if (layers) Object.values(layers).forEach((layer) => map.removeLayer(layer));
    layers = null;
  }

  function show(spec) {
    remove();
    radius = spec.radiusMeters;
    layers = buildLayers(map, spec);
    wireDrag(map, layers, { moveTo, placeHandle, onRadius, setRadiusState: (m) => { radius = m; } });
  }

  return {
    show,
    remove,
    startPick: () => layers && picker.start(),
    stopPick: picker.stop,
    isPicking: picker.isPicking,
    isShown: () => Boolean(layers),
    /** Move the centre without telling the sheet (it already knows). */
    setCentre: (latlng) => layers && moveTo(L.latLng(latlng.lat, latlng.lng), false),
    setRadius(m) {
      if (!layers) return;
      radius = m;
      layers.circle.setRadius(m);
      placeHandle();
    },
    setColor: (color) => layers && layers.circle.setStyle({ color }),
    /** Fit the circle in view. */
    fit: () => layers && map.fitBounds(layers.circle.getBounds().pad(0.4), { maxZoom: 17 }),
  };
}
