/*
 * Places tab: the add/edit dialog and crosshair-click flow.
 *
 * Purpose    : Build and drive the reused <dialog> that creates or edits one
 *              place (name/radius/color/confirmations), plus the map
 *              crosshair click that starts an add. Split out of places.js at
 *              the PRI rule-7 300-line file cap.
 * Inputs     : A Leaflet map handed in by `initDialog()`; place data handed
 *              in per call (places.js owns the place/circle registries).
 * Outputs    : POST/PUT /api/places(/{id}) on save.
 * Constraints: Every element is built with createElement/textContent, never
 *              raw markup. `initDialog()`'s `onSaved` callback is how this
 *              module tells places.js to reload — it never imports
 *              places.js itself, so the two files have one dependency
 *              direction, not a cycle.
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";

let map = null;
let onSaved = null;
let previewCircle = null;
let dialogEl = null;
let fields = null;

/** Called once by places.js's init() before any dialog function is used. */
export function initDialog(mapArg, { onSaved: onSavedArg }) {
  map = mapArg;
  onSaved = onSavedArg;
}

function button(text, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = text;
  btn.addEventListener("click", onClick);
  return btn;
}

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

  form.append(labeled(t("places.nameLabel"), name), lat, lon);
  const radiusLabel = document.createElement("label");
  radiusLabel.textContent = t("places.radiusLabel");
  radiusLabel.append(radius, radiusOut);
  form.append(
    radiusLabel,
    labeled(t("places.colorLabel"), color),
    labeled(t("places.enterConfirmations"), enter),
    labeled(t("places.exitConfirmations"), exit),
  );

  const errorEl = document.createElement("p");
  errorEl.className = "fp-dialog-error";
  errorEl.id = "fp-place-dialog-error";

  const footer = document.createElement("footer");
  const saveBtn = button(t("common.save"), onSave);
  const cancelBtn = button(t("common.cancel"), onCancel);
  footer.append(saveBtn, cancelBtn);
  form.append(errorEl, footer);

  dlg.appendChild(form);
  document.body.appendChild(dlg);

  fields = { name, lat, lon, radius, radiusOut, color, enter, exit, error: errorEl };
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
  fields.error.textContent = "";
  drawPreview(latlng, radius);
  dlg.showModal();
}

export function showAddDialog(latlng) {
  fillDialog("add", null, null, latlng);
}

/** places.js's editPlace() looks the place up (it owns the registry) and hands it here. */
export function openEditDialog(id, place) {
  fillDialog("edit", id, place, { lat: place.latitude, lng: place.longitude });
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
    if (onSaved) await onSaved();
  } catch (err) {
    // api() shows the lock screen for a 401; anything else (409, 422) is shown here.
    if (err.message !== "Locked") fields.error.textContent = err.message;
  }
}

function onCancel() {
  dialogEl.close();
  deactivateCrosshairMode();
}

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

/**
 * Blank the add/edit dialog's inputs.
 *
 * Closing the <dialog> only stops it being displayed. Its inputs keep their
 * values, and fields.lat/fields.lon hold the exact coordinates of the last
 * place the user opened — readable from DevTools the moment the lock screen
 * is up, which is precisely what purgeRenderedData()'s invariant forbids
 * (PROMPT.md §2 invariant 11). The dataset entries go too: editId names a
 * real place row.
 */
function clearDialogFields() {
  if (!fields) return;
  fields.name.value = "";
  fields.lat.value = "";
  fields.lon.value = "";
  fields.radius.value = "200";
  fields.radiusOut.textContent = "200";
  fields.color.value = "#3b82f6";
  fields.enter.value = "2";
  fields.exit.value = "2";
  fields.error.textContent = "";
  if (dialogEl) {
    delete dialogEl.dataset.editId;
    delete dialogEl.dataset.mode;
  }
}

/** places.js's purge() hook for the dialog's own state. */
export function purgeDialog() {
  removePreviewCircle();
  if (dialogEl && dialogEl.open) dialogEl.close();
  clearDialogFields();
}
