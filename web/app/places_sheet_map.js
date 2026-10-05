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

/**
 * Build the preview layers. Returns the control object; nothing is on the
 * map until `show()` is called.
 */
export function createSheetPreview(map, { onMove, onRadius }) {
  let marker = null;
  let circle = null;
  let handle = null;
  let radius = 100;
  let picking = false;

  const centre = () => marker.getLatLng();
  const placeHandle = () => handle.setLatLng(destinationPoint(centre(), radius, HANDLE_BEARING));

  function moveTo(next, notify = true) {
    marker.setLatLng(next);
    circle.setLatLng(next);
    placeHandle();
    if (notify) onMove({ lat: next.lat, lng: next.lng });
  }

  function onMapClick(e) {
    if (!picking) return;
    stopPick();
    moveTo(e.latlng);
  }

  function stopPick() {
    picking = false;
    map.getContainer().classList.remove("fp-picking");
    map.off("click", onMapClick);
  }

  function startPick() {
    if (!marker) return;
    picking = true;
    map.getContainer().classList.add("fp-picking");
    map.on("click", onMapClick);
  }

  function show({ latlng, radiusMeters, color }) {
    remove();
    radius = radiusMeters;
    const at = L.latLng(latlng.lat, latlng.lng);
    circle = L.circle(at, { radius, color, weight: 2, fillOpacity: 0.14, keyboard: false, interactive: false }).addTo(map);
    marker = L.marker(at, { draggable: true, keyboard: false }).addTo(map);
    const icon = L.divIcon({ className: "fp-map-pick-radius-handle", iconSize: [14, 14] });
    handle = L.marker(destinationPoint(at, radius, HANDLE_BEARING), { draggable: true, keyboard: false, icon }).addTo(map);
    marker.on("drag", () => moveTo(marker.getLatLng()));
    handle.on("drag", () => {
      const measured = Math.round(map.distance(centre(), handle.getLatLng()));
      radius = Math.min(MAX_RADIUS_M, Math.max(MIN_RADIUS_M, measured));
      circle.setRadius(radius);
      onRadius(radius);
    });
    handle.on("dragend", placeHandle);
    wireKeyboard(marker, ([dLat, dLng]) => moveTo({ lat: centre().lat + dLat, lng: centre().lng + dLng }));
  }

  function remove() {
    stopPick();
    [marker, circle, handle].forEach((layer) => layer && map.removeLayer(layer));
    marker = circle = handle = null;
  }

  return {
    show,
    remove,
    startPick,
    stopPick,
    isPicking: () => picking,
    isShown: () => Boolean(marker),
    /** Move the centre without telling the sheet (it already knows). */
    setCentre: (latlng) => marker && moveTo(L.latLng(latlng.lat, latlng.lng), false),
    setRadius(m) {
      if (!circle) return;
      radius = m;
      circle.setRadius(m);
      placeHandle();
    },
    setColor: (color) => circle && circle.setStyle({ color }),
    /** Fit the circle in view (the map may be partly covered by the bottom sheet on a phone). */
    fit: () => circle && map.fitBounds(circle.getBounds().pad(0.4), { maxZoom: 17 }),
  };
}
