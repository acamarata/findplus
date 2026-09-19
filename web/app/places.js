/*
 * Places tab: geofence circles, add/edit/delete dialog, presence chips.
 *
 * Purpose    : Surface E5's places/geofence engine — draw saved places as
 *              L.Circle layers, let the user create/edit them via a
 *              crosshair-click dialog, and inject a presence chip into each
 *              device row showing which place a tracker is inside.
 * Inputs     : GET /api/places, GET /api/places/presence; POST/PUT/DELETE
 *              /api/places(/{id}) on save/edit/delete.
 * Outputs    : A Leaflet layer group of place circles; a reused <dialog>;
 *              .fp-presence-chip spans appended to device rows.
 * Constraints: Every element below is built with createElement/textContent,
 *              never raw markup assignment, so API-sourced strings can never
 *              run as script. Acyclic: imports nothing from devices.js or
 *              main.js.
 */
"use strict";

import { api } from "./api.js";

let map = null;
let placeLayer = null;
let previewCircle = null;
let placesById = new Map();
let circlesById = new Map();
let dialogEl = null;
let fields = null;

export function init(mapArg, _deviceListEl) {
  map = mapArg;
  placeLayer = L.layerGroup().addTo(map);
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

/* --------------------------------------------------------------- dialog */

function field(type, attrs) {
  const el = document.createElement("input");
  el.type = type;
  Object.assign(el, attrs);
  return el;
}

function labeled(text, input) {
  const label = document.createElement("label");
  label.textContent = text;
  label.appendChild(input);
  return label;
}

function ensureDialog() {
  if (dialogEl) return dialogEl;

  const dlg = document.createElement("dialog");
  dlg.id = "fp-place-dialog";
  const form = document.createElement("form");
  form.method = "dialog";

  const name = field("text", { required: true });
  const lat = field("hidden", {});
  const lon = field("hidden", {});
  const radius = field("range", { min: "50", max: "5000", step: "10", value: "200" });
  const color = field("color", { value: "#3b82f6" });
  const enter = field("number", { min: "1", value: "2" });
  const exit = field("number", { min: "1", value: "2" });
  const radiusOut = document.createElement("output");
  radiusOut.textContent = radius.value;

  form.append(labeled("Name", name), lat, lon);
  const radiusLabel = document.createElement("label");
  radiusLabel.textContent = "Radius (m)";
  radiusLabel.append(radius, radiusOut);
  form.append(
    radiusLabel,
    labeled("Color", color),
    labeled("Enter confirmations", enter),
    labeled("Exit confirmations", exit),
  );

  const footer = document.createElement("footer");
  const saveBtn = button("Save", onSave);
  const cancelBtn = button("Cancel", onCancel);
  footer.append(saveBtn, cancelBtn);
  form.appendChild(footer);

  dlg.appendChild(form);
  document.body.appendChild(dlg);

  fields = { name, lat, lon, radius, radiusOut, color, enter, exit };
  dialogEl = dlg;

  radius.addEventListener("input", () => {
    radiusOut.textContent = radius.value;
    updatePreviewCircle();
  });
  dlg.addEventListener("close", removePreviewCircle);

  return dlg;
}

function drawPreview(latlng, radiusMeters) {
  removePreviewCircle();
  previewCircle = L.circle([latlng.lat, latlng.lng], { radius: radiusMeters, color: "#94a3b8" }).addTo(map);
}

function updatePreviewCircle() {
  if (!previewCircle) return;
  drawPreview(previewCircle.getLatLng(), Number(fields.radius.value));
}

function removePreviewCircle() {
  if (previewCircle) {
    map.removeLayer(previewCircle);
    previewCircle = null;
  }
}

function fillDialog(mode, id, place, latlng) {
  const dlg = ensureDialog();
  dlg.dataset.mode = mode;
  if (mode === "edit") dlg.dataset.editId = String(id);
  else delete dlg.dataset.editId;
  fields.name.value = place ? place.name : "";
  fields.lat.value = String(latlng.lat);
  fields.lon.value = String(latlng.lng);
  const radius = place ? place.radius_meters : 200;
  fields.radius.value = String(radius);
  fields.radiusOut.textContent = String(radius);
  fields.color.value = place ? place.color : "#3b82f6";
  fields.enter.value = String(place ? place.enter_confirmations : 2);
  fields.exit.value = String(place ? place.exit_confirmations : 2);
  drawPreview(latlng, radius);
  dlg.showModal();
}

export function showAddDialog(latlng) {
  fillDialog("add", null, null, latlng);
}

export async function editPlace(id) {
  const place = placesById.get(String(id));
  if (!place) return;
  fillDialog("edit", id, place, { lat: place.latitude, lng: place.longitude });
}

export async function deletePlace(id) {
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

async function onSave() {
  const dlg = dialogEl;
  const body = {
    name: fields.name.value,
    latitude: Number(fields.lat.value),
    longitude: Number(fields.lon.value),
    radius_meters: Number(fields.radius.value),
    color: fields.color.value,
    enter_confirmations: Number(fields.enter.value),
    exit_confirmations: Number(fields.exit.value),
  };
  const opts = { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  try {
    if (dlg.dataset.mode === "edit") {
      await api(`/api/places/${dlg.dataset.editId}`, { ...opts, method: "PUT" });
    } else {
      await api("/api/places", { ...opts, method: "POST" });
    }
    dlg.close();
    await loadPlaces();
  } catch (_) {
    // api() already surfaced the lock screen or left an error on screen;
    // the dialog stays open with the user's input so nothing is lost.
  }
}

function onCancel() {
  dialogEl.close();
  deactivateCrosshairMode();
}

/* ----------------------------------------------------------- crosshair */

export function activateCrosshairMode() {
  document.getElementById("map").classList.add("fp-crosshair-mode");
  map.once("click", (e) => {
    deactivateCrosshairMode();
    showAddDialog(e.latlng);
  });
}

function deactivateCrosshairMode() {
  document.getElementById("map").classList.remove("fp-crosshair-mode");
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
