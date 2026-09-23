/*
 * Places tab: the add/edit dialog.
 *
 * Purpose    : Build and drive the reused <dialog> that creates or edits one
 *              place (name/radius/colour/confirmations). Split out of
 *              places.js at the PRI rule-7 300-line file cap.
 * Inputs     : A Leaflet map handed in by `initDialog()`; place data handed
 *              in per call (places.js owns the place/circle registries).
 * Outputs    : POST/PUT /api/places(/{id}) on save.
 * Constraints: Every element is built with createElement/textContent, never
 *              raw markup. `initDialog()`'s `onSaved` callback is how this
 *              module tells places.js to reload — no places.js import here.
 *
 * UAT U3/U4/U10: the dialog used to be four bare, unstyled `<label>` rows and
 * needed a map click to open at all. It now gets the shared dialog chrome and
 * opens at the map's current centre, so "Add place" alone is enough;
 * `place_locator.js`'s tracker picker and address search move that starting
 * point somewhere real (UAT2 N8: with visible feedback once they do).
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";
import { createColorPicker } from "./components/color-picker.js";
import { createPlaceLocator } from "./components/place_locator.js";

const DEFAULT_COLOR = "#3b82f6";
const DEFAULT_RADIUS = "200";
const PREVIEW_COLOR = "#94a3b8";

let map = null;
let onSaved = null;
let previewCircle = null;
let dialogEl = null;
let fields = null;
let colorPicker = null;
let locator = null;

/** Called once by places.js's init() before any dialog function is used. */
export function initDialog(mapArg, { onSaved: onSavedArg }) {
  map = mapArg;
  onSaved = onSavedArg;
}

function button(text, onClick, className) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = text;
  if (className) btn.className = className;
  btn.addEventListener("click", onClick);
  return btn;
}

function field(type, attrs) {
  const el = document.createElement("input");
  el.type = type;
  Object.assign(el, attrs);
  return el;
}

/** A `.fp-dialog-field` row — the same wrapper the device/group editors use. */
function labeled(text, input, id) {
  const label = document.createElement("label");
  if (id) label.htmlFor = id;
  label.textContent = text;
  const wrap = document.createElement("div");
  wrap.className = "fp-dialog-field";
  wrap.append(label, input);
  return wrap;
}

function pickerGroup(legendText) {
  const group = document.createElement("fieldset");
  group.className = "fp-dialog-group";
  const legend = document.createElement("legend");
  legend.textContent = legendText;
  group.appendChild(legend);
  return group;
}

/** The name/lat/lon/radius/colour/confirmation inputs, built once. */
function buildPlaceFields() {
  const title = document.createElement("h2");
  title.id = "fp-place-dialog-title";
  const name = field("text", { id: "fp-place-name", required: true, maxLength: 80 });
  const lat = field("hidden", { id: "fp-place-lat" });
  const lon = field("hidden", { id: "fp-place-lon" });
  const radius = field("range", {
    id: "fp-place-radius", min: "50", max: "5000", step: "10", value: DEFAULT_RADIUS,
  });
  const color = field("hidden", { id: "fp-place-color", value: DEFAULT_COLOR });
  const enter = field("number", { id: "fp-place-enter", min: "1", value: "2" });
  const exit = field("number", { id: "fp-place-exit", min: "1", value: "2" });
  const radiusOut = document.createElement("output");
  radiusOut.htmlFor = radius.id;
  radiusOut.textContent = radius.value;
  const error = document.createElement("p");
  error.className = "fp-dialog-error";
  error.id = "fp-place-dialog-error";
  return { title, name, lat, lon, radius, color, enter, exit, radiusOut, error };
}

function radiusRow(f) {
  const label = document.createElement("label");
  label.htmlFor = f.radius.id;
  label.textContent = t("places.radiusLabel");
  const wrap = document.createElement("div");
  wrap.className = "fp-dialog-field";
  wrap.append(label, f.radius, f.radiusOut);
  return wrap;
}

/** Assemble the <form> around the built fields, the locator section and the colour picker. */
function buildPlaceForm(f, colorGroup, locatorHost) {
  const form = document.createElement("form");
  form.method = "dialog";

  form.append(
    f.title,
    labeled(t("places.nameLabel"), f.name, f.name.id),
    f.lat,
    f.lon,
    f.color,
    locatorHost,
    radiusRow(f),
    colorGroup,
    labeled(t("places.enterConfirmations"), f.enter, f.enter.id),
    labeled(t("places.exitConfirmations"), f.exit, f.exit.id),
  );

  const footer = document.createElement("footer");
  footer.append(
    button(t("common.save"), onSave, "btn"),
    button(t("common.cancel"), onCancel, "btn-secondary"),
  );
  form.append(f.error, footer);

  return form;
}

/** place_locator.js's onPick: move the map and redraw the preview (UAT2 N8). */
function applyPickedLocation({ latitude, longitude }) {
  fields.lat.value = String(latitude);
  fields.lon.value = String(longitude);
  map.setView([latitude, longitude], Math.max(map.getZoom(), 15));
  drawPreview({ lat: latitude, lng: longitude }, Number(fields.radius.value));
}

function ensureDialog() {
  if (dialogEl) return dialogEl;

  const dlg = document.createElement("dialog");
  dlg.id = "fp-place-dialog";
  // Names the dialog for a screen reader (same fix as the device/group editors).
  dlg.setAttribute("aria-labelledby", "fp-place-dialog-title");

  const f = buildPlaceFields();
  const colorGroup = pickerGroup(t("places.colorLabel"));
  const locatorHost = document.createElement("div");
  const loc = createPlaceLocator(locatorHost, { onPick: applyPickedLocation });

  const form = buildPlaceForm(f, colorGroup, locatorHost);
  dlg.appendChild(form);
  document.body.appendChild(dlg);

  fields = f;
  dialogEl = dlg;
  locator = loc;
  colorPicker = createColorPicker(colorGroup, {
    value: f.color.value,
    onChange: (value) => {
      f.color.value = value;
    },
    customLabel: t("places.field.customColor"),
  });

  f.radius.addEventListener("input", () => {
    f.radiusOut.textContent = f.radius.value;
    updatePreviewCircle();
  });
  dlg.addEventListener("close", removePreviewCircle);

  return dlg;
}

function drawPreview(latlng, radiusMeters) {
  removePreviewCircle();
  previewCircle = L.circle([latlng.lat, latlng.lng], {
    radius: radiusMeters, color: PREVIEW_COLOR, keyboard: false,
  }).addTo(map);
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
  fields.title.textContent =
    mode === "edit" ? t("places.dialog.title_edit", { name: place.name }) : t("places.dialog.title_add");
  fields.name.value = place ? place.name : "";
  fields.lat.value = String(latlng.lat);
  fields.lon.value = String(latlng.lng);
  const radius = place ? place.radius_meters : Number(DEFAULT_RADIUS);
  fields.radius.value = String(radius);
  fields.radiusOut.textContent = String(radius);
  const color = place ? place.color : DEFAULT_COLOR;
  fields.color.value = color;
  colorPicker.setValue(color);
  fields.enter.value = String(place ? place.enter_confirmations : 2);
  fields.exit.value = String(place ? place.exit_confirmations : 2);
  fields.error.textContent = "";
  locator.refreshTrackers();
  locator.reset();
  drawPreview(latlng, radius);
  dlg.showModal();
}

/** Opens the add dialog at `latlng` (U4/U10: no map click required). */
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
}

/**
 * Blank the add/edit dialog's inputs. Closing the <dialog> only hides it —
 * fields.lat/lon and the locator's search text are real location data left
 * readable from DevTools behind the lock screen otherwise (PROMPT.md §2
 * invariant 11).
 */
function clearDialogFields() {
  if (!fields) return;
  fields.name.value = "";
  fields.lat.value = "";
  fields.lon.value = "";
  fields.radius.value = DEFAULT_RADIUS;
  fields.radiusOut.textContent = DEFAULT_RADIUS;
  fields.color.value = DEFAULT_COLOR;
  fields.enter.value = "2";
  fields.exit.value = "2";
  fields.error.textContent = "";
  if (colorPicker) colorPicker.setValue(DEFAULT_COLOR);
  if (locator) locator.reset();
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
