/*
 * Place dialog: "Pick on map" -- a draggable marker and radius circle drawn
 * directly on the shared dashboard map (UAT6 N13).
 *
 * Purpose    : Let a place's location be set by clicking or tapping the real
 *              map, not just a tracker fix or an address search. A
 *              `<dialog open>` backdrops the whole page while it is modal,
 *              so the map underneath cannot be clicked at all until the
 *              caller closes it first -- this module only ever runs after
 *              that, and only ever draws on `map`; it never touches the
 *              dialog or its fields itself.
 * Inputs     : The shared Leaflet `map`, an optional starting point/radius/
 *              colour, and onConfirm/onCancel callbacks.
 * Outputs    : onConfirm({ latitude, longitude, radiusMeters }) once, or
 *              onCancel() once -- never both, and never more than once.
 *              Returns { abort() } so a caller that must tear this down
 *              without treating it as a user cancel (places_dialog.js's
 *              purgeDialog() on lock) can do that without re-showing
 *              anything.
 * Constraints: Every element is built with createElement/setAttribute, never
 *              raw markup. Keyboard: the marker is the one focusable element
 *              pick mode adds and is focused as soon as it starts, so arrow
 *              keys nudge it with no pointer at all (N13's keyboard bar);
 *              Enter confirms, Escape cancels, matching the on-map buttons.
 */
"use strict";

import { t } from "../i18n.js";

const NUDGE_DEGREES = 0.0002; // ~22 m of latitude -- the radius slider handles precision after.
const EARTH_RADIUS_M = 6378137;
const RADIUS_HANDLE_BEARING = 90; // due east of the centre
const MIN_RADIUS_M = 50;
const MAX_RADIUS_M = 5000;

/** Great-circle destination point `meters` from `latlng` along `bearingDeg`
 * (0 = north, 90 = east). Used to keep the radius handle sitting exactly on
 * the circle's own edge -- after the centre moves, and again once a drag
 * ends -- rather than wherever the pointer happened to let go (UAT7-N12). */
function destinationPoint(latlng, meters, bearingDeg) {
  const bearing = (bearingDeg * Math.PI) / 180;
  const lat1 = (latlng.lat * Math.PI) / 180;
  const lng1 = (latlng.lng * Math.PI) / 180;
  const angDist = meters / EARTH_RADIUS_M;
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(angDist) + Math.cos(lat1) * Math.sin(angDist) * Math.cos(bearing),
  );
  const lng2 =
    lng1 +
    Math.atan2(
      Math.sin(bearing) * Math.sin(angDist) * Math.cos(lat1),
      Math.cos(angDist) - Math.sin(lat1) * Math.sin(lat2),
    );
  return L.latLng((lat2 * 180) / Math.PI, (lng2 * 180) / Math.PI);
}

/** The draggable grip on the circle's edge (UAT7-N12): dragging it resizes
 * `circle` live, clamped to the same 50-5000 m range the dialog's own slider
 * enforces. `getCenter` is a thunk (not a point) so the handle always resizes
 * around wherever the marker currently is, even if it moved after this was
 * built. `recenter()` is `startMapPick`'s own `moveTo` keeping the handle on
 * the edge when the marker itself is dragged or nudged. */
function createRadiusHandle(map, circle, getCenter, initialRadius) {
  let radius = initialRadius;
  const icon = L.divIcon({ className: "fp-map-pick-radius-handle", iconSize: [14, 14] });
  const handle = L.marker(destinationPoint(getCenter(), radius, RADIUS_HANDLE_BEARING), {
    draggable: true,
    keyboard: false,
    icon,
  }).addTo(map);

  handle.on("drag", () => {
    const measured = map.distance(getCenter(), handle.getLatLng());
    radius = Math.min(MAX_RADIUS_M, Math.max(MIN_RADIUS_M, Math.round(measured)));
    circle.setRadius(radius);
  });
  // Snaps back onto the circle's own edge: a drag past the clamp, or one that
  // did not end exactly due east, would otherwise leave the handle floating
  // off the circle it is supposed to resize.
  handle.on("dragend", () => handle.setLatLng(destinationPoint(getCenter(), radius, RADIUS_HANDLE_BEARING)));

  return {
    recenter: () => handle.setLatLng(destinationPoint(getCenter(), radius, RADIUS_HANDLE_BEARING)),
    remove: () => map.removeLayer(handle),
    getRadius: () => radius,
  };
}

function buildControl({ onConfirm, onCancel }) {
  // UAT7-N03: at 1280x800 the map runs to ~870px and bottomleft put the
  // control below the fold, so only the first instructions line was ever on
  // screen -- a mouse user had to scroll to find "Set location"/"Cancel" at
  // all. topright is Leaflet's own free corner (zoom stays topleft, layers
  // would be topright too but this app has none), so it never overlaps
  // another control and always sits inside the visible map area.
  const control = L.control({ position: "topright" });
  control.onAdd = () => {
    const container = L.DomUtil.create("div", "leaflet-control fp-map-pick-control");
    // Without these, a click or a scroll on the control reaches the map
    // underneath too -- moving the marker (or panning) instead of, or as
    // well as, hitting the button under the pointer.
    L.DomEvent.disableClickPropagation(container);
    L.DomEvent.disableScrollPropagation(container);

    const p = document.createElement("p");
    p.textContent = t("places.mapPick.instructions");

    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = "btn btn-tiny";
    confirmBtn.textContent = t("places.mapPick.setLocation");
    confirmBtn.addEventListener("click", onConfirm);

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "btn-secondary btn-tiny";
    cancelBtn.textContent = t("common.cancel");
    cancelBtn.addEventListener("click", onCancel);

    const row = document.createElement("div");
    row.className = "fp-map-pick-actions";
    row.append(confirmBtn, cancelBtn);
    container.append(p, row);
    return container;
  };
  return control;
}

/** Arrow keys nudge the marker; Enter confirms; Escape cancels -- the
 * keyboard path N13 asks for as an alternative to dragging or clicking. */
function wireKeyboard(markerEl, { onNudge, onConfirm, onCancel }) {
  markerEl.classList.add("fp-map-pick-marker");
  markerEl.tabIndex = 0;
  markerEl.setAttribute("role", "button");
  markerEl.setAttribute("aria-label", t("places.mapPick.markerLabel"));
  const deltas = {
    ArrowUp: [NUDGE_DEGREES, 0],
    ArrowDown: [-NUDGE_DEGREES, 0],
    ArrowLeft: [0, -NUDGE_DEGREES],
    ArrowRight: [0, NUDGE_DEGREES],
  };
  markerEl.addEventListener("keydown", (e) => {
    if (deltas[e.key]) {
      e.preventDefault();
      onNudge(deltas[e.key]);
    } else if (e.key === "Enter") {
      e.preventDefault();
      onConfirm();
    } else if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    }
  });
}

/** Wires a map click and a marker drag to the same `moveTo`, and returns the
 * click handler so the caller can `map.off("click", ...)` it again later. */
function wireMovement(map, marker, moveTo) {
  function onMapClick(e) {
    moveTo(e.latlng);
  }
  map.on("click", onMapClick);
  marker.on("drag", () => moveTo(marker.getLatLng()));
  return onMapClick;
}

/** Focuses the marker's element and wires the keyboard bar to it, if Leaflet
 * has rendered one yet -- split out of `startMapPick` to keep it under the
 * PRI 50-line/function cap. */
function focusWithKeyboard(marker, { onNudge, onConfirm, onCancel }) {
  const markerEl = marker.getElement();
  if (!markerEl) return;
  wireKeyboard(markerEl, { onNudge, onConfirm, onCancel });
  markerEl.focus();
}

/**
 * Start crosshair mode on `map`. The caller must already have closed
 * whatever dialog was covering it -- see places_dialog.js's beginMapPick().
 */
export function startMapPick(map, { latlng, radiusMeters, color, onConfirm, onCancel }) {
  let current = latlng ? L.latLng(latlng) : map.getCenter();
  const marker = L.marker(current, { draggable: true, keyboard: false }).addTo(map);
  const circle = L.circle(current, { radius: radiusMeters, color, keyboard: false }).addTo(map);
  // UAT7-N12: the circle itself can now be resized on the map, not only from
  // the dialog's slider (which is not even on screen while pick mode has it
  // closed) -- getCenter reads `current` live so the handle keeps tracking
  // the marker if it moves after this is built.
  const radiusHandle = createRadiusHandle(map, circle, () => current, radiusMeters);

  function moveTo(next) {
    current = L.latLng(next);
    marker.setLatLng(current);
    circle.setLatLng(current);
    radiusHandle.recenter();
  }
  const onMapClick = wireMovement(map, marker, moveTo);

  /** Removes every trace of pick mode from the map without calling either
   * callback -- the one path purgeDialog() uses on lock (real coordinates
   * must not linger in a dangling marker behind the lock screen either). */
  function abort() {
    map.off("click", onMapClick);
    map.removeLayer(marker);
    map.removeLayer(circle);
    radiusHandle.remove();
    control.remove();
  }

  function confirm() {
    const picked = { latitude: current.lat, longitude: current.lng, radiusMeters: radiusHandle.getRadius() };
    abort();
    onConfirm(picked);
  }
  function cancel() {
    abort();
    onCancel();
  }

  const control = buildControl({ onConfirm: confirm, onCancel: cancel });
  control.addTo(map);

  focusWithKeyboard(marker, {
    onNudge: ([dLat, dLng]) => moveTo({ lat: current.lat + dLat, lng: current.lng + dLng }),
    onConfirm: confirm,
    onCancel: cancel,
  });

  return { abort };
}
