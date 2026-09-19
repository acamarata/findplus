/*
 * Places tab: geofence circles + presence chips. The add/edit dialog and
 * crosshair-click flow live in places_dialog.js (split out at the PRI
 * rule-7 300-line file cap).
 *
 * Purpose    : Surface E5's places/geofence engine — draw saved places as
 *              L.Circle layers, own the place/circle registries, and inject
 *              a presence chip into each device row showing which place a
 *              tracker is inside.
 * Inputs     : GET /api/places, GET /api/places/presence; DELETE
 *              /api/places/{id} on delete (add/edit POST/PUT is
 *              places_dialog.js's).
 * Outputs    : A Leaflet layer group of place circles; .fp-presence-chip
 *              spans appended to device rows.
 * Constraints: Every element below is built with createElement/textContent,
 *              never raw markup assignment, so API-sourced strings can never
 *              run as script. Acyclic: imports nothing from devices.js or
 *              main.js.
 */
"use strict";

import { api } from "./api.js";
import { activateCrosshairMode, initDialog, openEditDialog, purgeDialog } from "./places_dialog.js";

let map = null;
let placeLayer = null;
let placesById = new Map();
let circlesById = new Map();

export function init(mapArg, _deviceListEl) {
  map = mapArg;
  placeLayer = L.layerGroup().addTo(map);
  initDialog(map, { onSaved: loadPlaces });
  const addBtn = document.getElementById("fp-add-place-btn");
  if (addBtn) addBtn.addEventListener("click", activateCrosshairMode);
  refreshAll();
}

export async function refreshAll() {
  try {
    await loadPlaces();
    await loadPresence();
  } catch (_) {
    // Locked or unreachable at boot; the lock screen / next refresh handles it.
  }
}

/** lock.js purgeRenderedData() hook: a circle or chip left behind is real location data. */
export function purge() {
  if (placeLayer) placeLayer.clearLayers();
  purgeDialog();
  placesById = new Map();
  circlesById.clear();
  document.querySelectorAll(".fp-presence-chip").forEach((chip) => chip.remove());
}

export async function loadPlaces() {
  const places = await api("/api/places");
  placeLayer.clearLayers();
  circlesById.clear();
  placesById = new Map(places.map((p) => [String(p.id), p]));
  places.forEach((place) => {
    const circle = L.circle([place.latitude, place.longitude], {
      radius: place.radius_meters, color: place.color, fillOpacity: 0.15,
    }).bindPopup(buildPlacePopup(place));
    circle.addTo(placeLayer);
    circlesById.set(String(place.id), circle);
  });
}

function button(text, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = text;
  btn.addEventListener("click", onClick);
  return btn;
}

function buildPlacePopup(place) {
  const box = document.createElement("div");
  box.className = "fp-place-popup";
  const name = document.createElement("div");
  name.textContent = place.name;
  box.appendChild(name);
  box.appendChild(button("Edit", () => editPlace(place.id)));
  box.appendChild(button("Delete", () => deletePlace(place.id)));
  return box;
}

async function editPlace(id) {
  const place = placesById.get(String(id));
  if (!place) return;
  openEditDialog(id, place);
}

async function deletePlace(id) {
  const place = placesById.get(String(id));
  if (!window.confirm(`Delete place "${place ? place.name : id}"?`)) return;
  const res = await fetch(`/api/places/${id}`, { method: "DELETE" });
  if (!res.ok) return;
  const circle = circlesById.get(String(id));
  if (circle) {
    placeLayer.removeLayer(circle);
    circlesById.delete(String(id));
  }
  placesById.delete(String(id));
  await loadPresence();
}

/* ------------------------------------------------------------- presence */

export async function loadPresence() {
  let entries;
  try {
    entries = await api("/api/places/presence");
  } catch (_) {
    return;
  }
  entries
    .filter((entry) => entry.state === "inside")
    .forEach((entry) => {
      const row = document.querySelector(`[data-device-id="${entry.device_id}"]`);
      if (!row) return;
      let chip = row.querySelector(".fp-presence-chip");
      if (!chip) {
        chip = document.createElement("span");
        chip.className = "fp-presence-chip";
        row.appendChild(chip);
      }
      chip.textContent = `${entry.place_name} since ${relativeTime(entry.since_observed_at)}`;
    });
}

function relativeTime(iso) {
  if (!iso) return "unknown";
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours} h` : `${Math.floor(hours / 24)} d`;
}
