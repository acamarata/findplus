/*
 * Places tab: the add/edit place sheet.
 *
 * Purpose    : Build and drive the reused <dialog> that creates or edits one
 *              place (name/kind/location/radius/colour/alerts). U5: it is a
 *              non-modal sheet beside the live map (right-hand on a desktop,
 *              bottom on a phone) so the place's circle and centre marker are
 *              always visible and follow the radius, colour and centre as
 *              they change; "Use map centre" and "Pick on map" work without
 *              leaving it. With no map on screen (the setup wizard) it opens
 *              as an ordinary modal dialog. Element construction lives in
 *              places_dialog_dom.js, the map preview in places_sheet_map.js
 *              and the layout hooks in places_sheet_layout.js (PRI 300-line cap).
 * Inputs     : A Leaflet map handed in by `initDialog()`; place data handed
 *              in per call (places.js owns the place/circle registries).
 * Outputs    : POST/PUT /api/places(/{id}) on save.
 * Constraints: Every element is built with createElement/textContent, never
 *              raw markup. `initDialog()`'s `onSaved` callback is how this
 *              module tells places.js to reload — no places.js import here.
 *              Stable entry points: showAddDialog(), openEditDialog(),
 *              places.js's openPlaceSheet({mode, placeId}).
 */
"use strict";

import { t } from "./i18n.js";
import { createColorPicker } from "./components/color-picker.js";
import { createPlaceLocator } from "./components/place_locator.js";
import { duplicateNameMessage, placeValidationMessage, plainFailure } from "./dialog_errors.js";
import { buildDialog, radiusOf, setRadius, updateRadiusWarning, wireRadius } from "./places_dialog_dom.js";
import { showWhere, clearWhere, showUsage } from "./places_dialog_where.js";
import { submitPlace } from "./places_dialog_save.js";
import { guessKind, guessedFrom, syncKindHint } from "./places_kind.js";
import { fillNotify } from "./places_notify.js";
import { createSheetPreview } from "./places_sheet_map.js";
import { enterSheet, leaveSheet, mapIsVisible } from "./places_sheet_layout.js";

// The 12 palette colours (labels.py's DEVICE_PALETTE). A new place gets the first one no place uses (U6).
const PLACE_PALETTE = ["#4f8cf7", "#e7663f", "#37c67a", "#c77ae6", "#e7b53f", "#3fc9d6", "#e64f7a", "#8fb43f", "#f2994a", "#9b6bd6", "#4fd6a8", "#d65f5f"];

/** A new place's colour: the first palette colour not in `used` (an array of hex strings), else cycle by count. */
function defaultPlaceColour(used) {
  if (!Array.isArray(used)) return PLACE_PALETTE[(used || 0) % PLACE_PALETTE.length];
  const taken = new Set(used.map((c) => String(c).toLowerCase()));
  return PLACE_PALETTE.find((c) => !taken.has(c)) || PLACE_PALETTE[used.length % PLACE_PALETTE.length];
}
// UAT 11: a new place starts at the recommended 100 m, not 200 m.
const DEFAULT_RADIUS = "100";
// UAT7 N01: the one place a new place's confirmation defaults are written, so the
// dialog can never drift from create_place's own defaults (D17: enter=1, exit=2).
const DEFAULT_ENTER_CONFIRMATIONS = "1";
const DEFAULT_EXIT_CONFIRMATIONS = "2";

let map = null;
let onSaved = null;
let preview = null;
let dialogEl = null;
let fields = null;
let colorPicker = null;
let locator = null;

/** Called once by places.js's init() before any dialog function is used. */
export function initDialog(mapArg, { onSaved: onSavedArg }) {
  map = mapArg;
  onSaved = onSavedArg;
  preview = createSheetPreview(map, { onMove: onPreviewMove, onRadius: onPreviewRadius });
}

function ensureDialog() {
  if (dialogEl) return dialogEl;
  const { dlg, fields: f, colorGroup, locatorHost } = buildDialog({ onSave, onCancel });
  document.body.appendChild(dlg);
  fields = f;
  dialogEl = dlg;
  locator = createPlaceLocator(locatorHost, {
    onPick: applyPickedLocation,
    onPickOnMap: togglePick,
    onUseCentre: useMapCentre,
  });
  colorPicker = createColorPicker(colorGroup, {
    value: f.color.value || PLACE_PALETTE[0],
    allowCustom: false,
    onChange: (value) => {
      f.color.value = value;
      preview.setColor(value);
    },
  });
  wireRadius(f, () => preview.setRadius(radiusOf(fields)));
  f.name.addEventListener("input", () => {
    if (dlg.dataset.mode !== "add" || f.kind.select.dataset.touched) return;
    f.kind.select.value = guessKind(f.name.value);
    syncKindHint(f.kind, guessedFrom(f.name.value));
  });
  dlg.addEventListener("close", onClosed);
  dlg.addEventListener("keydown", onSheetKey);
  return dlg;
}

/** A non-modal <dialog> gets no native Escape: end pick mode first, then close. */
function onSheetKey(e) {
  if (e.key !== "Escape" || dialogEl.dataset.sheet !== "1") return;
  e.preventDefault();
  if (preview.isPicking()) {
    preview.stopPick();
    locator.setPicking(false);
  } else {
    dialogEl.close();
  }
}

function onClosed() {
  preview.remove();
  leaveSheet(map, dialogEl);
  locator.setPicking(false);
}

/** Put the typed location in the hidden fields and the where-line, and move the pin. */
function setLocation(lat, lng) {
  fields.lat.value = String(lat);
  fields.lon.value = String(lng);
  showWhere(fields.where, "picked", lat, lng);
}

/** The pin was dragged, or the map clicked in pick mode. */
function onPreviewMove({ lat, lng }) {
  setLocation(lat, lng);
  locator.setPicking(false);
  locator.showStatus(t("places.field.locationSetAt", { lat: lat.toFixed(4), lon: lng.toFixed(4) }));
}

/** The circle's edge grip was dragged: both radius inputs follow. */
function onPreviewRadius(metres) {
  setRadius(fields, metres);
  updateRadiusWarning(fields);
}

/** place_locator.js's onPick (tracker fix or address): move the pin and the map to it. */
function applyPickedLocation({ latitude, longitude }) {
  setLocation(latitude, longitude);
  preview.setCentre({ lat: latitude, lng: longitude });
  map.setView([latitude, longitude], Math.max(map.getZoom(), 15));
}

/** "Use map centre": the pin jumps to wherever the map is centred now. */
function useMapCentre() {
  const c = map.getCenter();
  setLocation(c.lat, c.lng);
  preview.setCentre(c);
  locator.showStatus(t("places.field.locationSetAt", { lat: c.lat.toFixed(4), lon: c.lng.toFixed(4) }));
}

/** "Pick on map": the next click on the map moves the pin; pressing again cancels. */
function togglePick() {
  if (preview.isPicking()) {
    preview.stopPick();
    locator.setPicking(false);
  } else {
    preview.startPick();
    locator.setPicking(true);
  }
}

/** The kind (the saved one, or a guess that follows the name until the owner picks) and the alert box. */
function fillKindAndNotify(mode, place) {
  const kind = fields.kind;
  kind.select.value = place ? place.kind || "other" : "other";
  delete kind.select.dataset.touched;
  syncKindHint(kind, Boolean(place && place.kind_guessed));
  fields.notify.wrap.hidden = mode === "edit";
  if (mode === "add") fillNotify(fields.notify);
}

function fillFields(mode, id, place, latlng, existingCount) {
  const dlg = dialogEl;
  dlg.dataset.mode = mode;
  if (mode === "edit") dlg.dataset.editId = String(id);
  else delete dlg.dataset.editId;
  fields.title.textContent =
    mode === "edit" ? t("places.dialog.title_edit", { name: place.name }) : t("places.dialog.title_add");
  fields.name.value = place ? place.name : "";
  fields.lat.value = String(latlng.lat);
  fields.lon.value = String(latlng.lng);
  setRadius(fields, place ? place.radius_meters : Number(DEFAULT_RADIUS));
  updateRadiusWarning(fields);
  const color = place ? place.color : defaultPlaceColour(existingCount);
  fields.color.value = color;
  colorPicker.setValue(color);
  fields.enter.value = place ? String(place.enter_confirmations) : DEFAULT_ENTER_CONFIRMATIONS;
  fields.exit.value = place ? String(place.exit_confirmations) : DEFAULT_EXIT_CONFIRMATIONS;
  dlg.querySelector("#fp-place-advanced").open = false;
  fillKindAndNotify(mode, place);
  fields.error.textContent = "";
}

function fillDialog(mode, id, place, latlng, existingCount, ruleCount = 0) {
  const dlg = ensureDialog();
  fillFields(mode, id, place, latlng, existingCount);
  showWhere(fields.where, mode === "edit" ? "current" : "centre", latlng.lat, latlng.lng);
  showUsage(fields.usage, mode === "edit" ? ruleCount : 0);
  locator.refreshTrackers();
  locator.reset();
  const sheet = mapIsVisible(map);
  if (sheet) enterSheet(map, dlg);
  else leaveSheet(map, dlg);
  preview.show({ latlng, radiusMeters: radiusOf(fields), color: fields.color.value });
  if (sheet) {
    dlg.show();
    if (mode === "edit") preview.fit();
  } else {
    dlg.showModal();
  }
  fields.name.focus({ preventScroll: true });
}

/** Opens the add sheet at `latlng` (U4/U10: no map click required).
 * `existingCount` (an array of the saved places' colours, or a count) picks this
 * place's default colour: the first palette colour no place uses yet (U6). */
export function showAddDialog(latlng, existingCount = 0) {
  fillDialog("add", null, null, latlng, existingCount);
}

/** places.js's editPlace() looks the place up (it owns the registry) and hands it here. */
export function openEditDialog(id, place, ruleCount = 0) {
  fillDialog("edit", id, place, { lat: place.latitude, lng: place.longitude }, 0, ruleCount);
}

async function onSave() {
  const dlg = dialogEl;
  const form = dlg.querySelector("form");
  // N16: an empty name (or an enter/exit count outside 1-5) is caught here,
  // with the browser's own inline message, before it reaches the server.
  if (!form.checkValidity()) {
    form.reportValidity();
    return;
  }
  try {
    const { saved, editing } = await submitPlace(dlg, fields);
    dlg.close();
    if (onSaved) await onSaved(saved, editing ? "edit" : "add");
  } catch (err) {
    // api() shows the lock screen for a 401. A 422 and a duplicate-name 409 get
    // their own sentences; anything else is one plain line, never raw server text (U29).
    if (err.message === "Locked") return;
    fields.error.textContent =
      placeValidationMessage(err) || duplicateNameMessage(err, "places.duplicateName") || plainFailure(err, "places.saveFailed");
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
  setRadius(fields, DEFAULT_RADIUS);
  fields.color.value = PLACE_PALETTE[0];
  fields.enter.value = DEFAULT_ENTER_CONFIRMATIONS;
  fields.exit.value = DEFAULT_EXIT_CONFIRMATIONS;
  fields.error.textContent = "";
  clearWhere(fields.where);
  showUsage(fields.usage, 0);
  if (colorPicker) colorPicker.setValue(PLACE_PALETTE[0]);
  if (locator) locator.reset();
  if (dialogEl) {
    delete dialogEl.dataset.editId;
    delete dialogEl.dataset.mode;
  }
}

/** places.js's purge() hook for the dialog's own state. */
export function purgeDialog() {
  if (preview) preview.remove();
  if (dialogEl && dialogEl.open) dialogEl.close();
  clearDialogFields();
}
