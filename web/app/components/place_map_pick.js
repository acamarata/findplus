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
 * Outputs    : onConfirm({ latitude, longitude }) once, or onCancel() once --
 *              never both, and never more than once. Returns { abort() } so
 *              a caller that must tear this down without treating it as a
 *              user cancel (places_dialog.js's purgeDialog() on lock) can do
 *              that without re-showing anything.
 * Constraints: Every element is built with createElement/setAttribute, never
 *              raw markup. Keyboard: the marker is the one focusable element
 *              pick mode adds and is focused as soon as it starts, so arrow
 *              keys nudge it with no pointer at all (N13's keyboard bar);
 *              Enter confirms, Escape cancels, matching the on-map buttons.
 */
"use strict";

import { t } from "../i18n.js";

const NUDGE_DEGREES = 0.0002; // ~22 m of latitude -- the radius slider handles precision after.

function buildControl({ onConfirm, onCancel }) {
  const control = L.control({ position: "bottomleft" });
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

/**
 * Start crosshair mode on `map`. The caller must already have closed
 * whatever dialog was covering it -- see places_dialog.js's beginMapPick().
 */
export function startMapPick(map, { latlng, radiusMeters, color, onConfirm, onCancel }) {
  let current = latlng ? L.latLng(latlng) : map.getCenter();
  const marker = L.marker(current, { draggable: true, keyboard: false }).addTo(map);
  const circle = L.circle(current, { radius: radiusMeters, color, keyboard: false }).addTo(map);

  function moveTo(next) {
    current = L.latLng(next);
    marker.setLatLng(current);
    circle.setLatLng(current);
  }
  const onMapClick = wireMovement(map, marker, moveTo);

  /** Removes every trace of pick mode from the map without calling either
   * callback -- the one path purgeDialog() uses on lock (real coordinates
   * must not linger in a dangling marker behind the lock screen either). */
  function abort() {
    map.off("click", onMapClick);
    map.removeLayer(marker);
    map.removeLayer(circle);
    control.remove();
  }

  function confirm() {
    const picked = { latitude: current.lat, longitude: current.lng };
    abort();
    onConfirm(picked);
  }
  function cancel() {
    abort();
    onCancel();
  }

  const control = buildControl({ onConfirm: confirm, onCancel: cancel });
  control.addTo(map);

  const markerEl = marker.getElement();
  if (markerEl) {
    wireKeyboard(markerEl, {
      onNudge: ([dLat, dLng]) => moveTo({ lat: current.lat + dLat, lng: current.lng + dLng }),
      onConfirm: confirm,
      onCancel: cancel,
    });
    markerEl.focus();
  }

  return { abort };
}
