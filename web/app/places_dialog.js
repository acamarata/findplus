/*
 * Places tab: the add/edit dialog.
 *
 * Purpose    : Build and drive the reused <dialog> that creates or edits one
 *              place (name/radius/colour/confirmations). Split out of
 *              places.js at the PRI rule-7 300-line file cap; element
 *              construction is further split into places_dialog_dom.js at
 *              the same cap, and "Pick on map" into
 *              components/place_map_pick.js.
 * Inputs     : A Leaflet map handed in by `initDialog()`; place data handed
 *              in per call (places.js owns the place/circle registries).
 * Outputs    : POST/PUT /api/places(/{id}) on save.
 * Constraints: Every element is built with createElement/textContent, never
 *              raw markup. `initDialog()`'s `onSaved` callback is how this
 *              module tells places.js to reload — no places.js import here.
 * UAT U3/U4/U10: the dialog used to be four bare, unstyled `<label>` rows and
 * needed a map click to open at all. It now gets the shared dialog chrome and
 * opens at the map's current centre, so "Add place" alone is enough;
 * `place_locator.js`'s tracker/map-pick/address locator moves that starting
 * point somewhere real (UAT2 N8: with visible feedback once it does).
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";
import { createColorPicker } from "./components/color-picker.js";
import { createPlaceLocator } from "./components/place_locator.js";
import { startMapPick } from "./components/place_map_pick.js";
import { duplicateNameMessage, placeValidationMessage } from "./dialog_errors.js";
import { buildDialog } from "./places_dialog_dom.js";

// N26: a same-default-blue place after another already existed made a new
// one hard to tell apart on the map circles' colour alone; showAddDialog()
// picks the next entry for a place that does not exist yet instead.
const PLACE_PALETTE = ["#3b82f6", "#e7663f", "#37c67a", "#c77ae6", "#e7b53f", "#3fc9d6", "#e64f7a", "#8fb43f"];
const DEFAULT_RADIUS = "200";
const PREVIEW_COLOR = "#94a3b8";
// UAT7 N01: the one place a new place's confirmation defaults are written,
// so the dialog can never drift from create_place's own defaults again
// (D17: enter=1, exit=2; PROMPT.md D17, places/repo.py create_place()).
// cli/tests/ui/test_place_map_pick.py pins these against the backend.
const DEFAULT_ENTER_CONFIRMATIONS = "1";
const DEFAULT_EXIT_CONFIRMATIONS = "2";

let map = null;
let onSaved = null;
let previewCircle = null;
let dialogEl = null;
let fields = null;
let colorPicker = null;
let locator = null;
// place_map_pick.js's abort() while a pick is in progress -- purgeDialog()
// must be able to end it on lock without treating that as a user Cancel
// (which would reopen the dialog behind the lock screen).
let activePick = null;

/** Called once by places.js's init() before any dialog function is used. */
export function initDialog(mapArg, { onSaved: onSavedArg }) {
  map = mapArg;
  onSaved = onSavedArg;
}

function ensureDialog() {
  if (dialogEl) return dialogEl;

  const { dlg, fields: f, colorGroup, locatorHost } = buildDialog({ onSave, onCancel });
  document.body.appendChild(dlg);

  fields = f;
  dialogEl = dlg;
  locator = createPlaceLocator(locatorHost, { onPick: applyPickedLocation, onPickOnMap: beginMapPick });
  colorPicker = createColorPicker(colorGroup, {
    value: f.color.value || PLACE_PALETTE[0],
    onChange: (value) => {
      f.color.value = value;
    },
    customLabel: t("places.field.customColor"),
  });

  // UAT7-N12: the slider and the number box stay in sync both ways. Setting
  // a range input's `.value` clamps it to its own min/max for free, so the
  // slider is always valid; the number box is only clamped back on `change`
  // (blur/Enter) so a value mid-typed (e.g. "5" on the way to "500") is not
  // fought keystroke by keystroke.
  f.radius.addEventListener("input", () => {
    f.radiusNumber.value = f.radius.value;
    updatePreviewCircle();
  });
  f.radiusNumber.addEventListener("input", () => {
    f.radius.value = f.radiusNumber.value;
    updatePreviewCircle();
  });
  f.radiusNumber.addEventListener("change", () => {
    f.radiusNumber.value = f.radius.value;
  });
  dlg.addEventListener("close", removePreviewCircle);

  return dlg;
}

/** place_locator.js's onPick: move the map and redraw the preview (UAT2 N8).
 * `radiusMeters`, only ever set by a map pick's own resize handle (UAT7-N12),
 * updates both radius inputs before the preview is drawn so it reflects the
 * radius actually picked rather than whatever the dialog had before. */
function applyPickedLocation({ latitude, longitude, radiusMeters }) {
  fields.lat.value = String(latitude);
  fields.lon.value = String(longitude);
  if (radiusMeters) {
    fields.radius.value = String(radiusMeters);
    fields.radiusNumber.value = fields.radius.value;
  }
  map.setView([latitude, longitude], Math.max(map.getZoom(), 15));
  drawPreview({ lat: latitude, lng: longitude }, Number(fields.radius.value));
}

/**
 * N13: "Pick on map" steps the dialog aside so the real map underneath is
 * clickable again -- a `<dialog>` open with showModal() backdrops the whole
 * page, so a crosshair click could never reach the map while the dialog
 * stayed open. close() only clears the preview circle (the 'close' listener
 * above); the fields keep whatever the user had already typed, and
 * fillDialog() (which would reset them) is never called again here.
 */
function beginMapPick() {
  const dlg = dialogEl;
  const hasPoint = fields.lat.value !== "" && fields.lon.value !== "";
  const initial = hasPoint ? { lat: Number(fields.lat.value), lng: Number(fields.lon.value) } : null;
  dlg.close();
  // UAT7-N03: on a short viewport the map itself can start below the fold
  // (e.g. scrolled down to reach "Add place"); bring it fully into view now
  // that the dialog's backdrop is gone, so the topright pick control never
  // needs a scroll to find.
  map.getContainer().scrollIntoView({ block: "nearest" });
  activePick = startMapPick(map, {
    latlng: initial,
    radiusMeters: Number(fields.radius.value),
    color: fields.color.value || PLACE_PALETTE[0],
    onConfirm: (picked) => {
      activePick = null;
      applyPickedLocation(picked);
      // UAT7-N12: "Location set from the map." hid a wrong pick until the
      // place was already saved -- the actual coordinates, to 4 decimal
      // places (~11 m), make a bad pick visible immediately.
      locator.showStatus(
        t("places.field.locationSetAt", {
          lat: picked.latitude.toFixed(4),
          lon: picked.longitude.toFixed(4),
        }),
      );
      dlg.showModal();
    },
    onCancel: () => {
      activePick = null;
      if (hasPoint) drawPreview(initial, Number(fields.radius.value));
      dlg.showModal();
    },
  });
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

function fillDialog(mode, id, place, latlng, existingCount) {
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
  fields.radiusNumber.value = String(radius);
  const color = place ? place.color : PLACE_PALETTE[(existingCount || 0) % PLACE_PALETTE.length];
  fields.color.value = color;
  colorPicker.setValue(color);
  fields.enter.value = place ? String(place.enter_confirmations) : DEFAULT_ENTER_CONFIRMATIONS;
  fields.exit.value = place ? String(place.exit_confirmations) : DEFAULT_EXIT_CONFIRMATIONS;
  fields.error.textContent = "";
  locator.refreshTrackers();
  locator.reset();
  drawPreview(latlng, radius);
  dlg.showModal();
}

/** Opens the add dialog at `latlng` (U4/U10: no map click required).
 * `existingCount` (places.js's own placesById.size) picks this place's
 * default colour (N26): the Nth place added gets the Nth palette entry
 * instead of every place starting the same blue. */
export function showAddDialog(latlng, existingCount = 0) {
  fillDialog("add", null, null, latlng, existingCount);
}

/** places.js's editPlace() looks the place up (it owns the registry) and hands it here. */
export function openEditDialog(id, place) {
  fillDialog("edit", id, place, { lat: place.latitude, lng: place.longitude }, 0);
}

async function onSave() {
  const dlg = dialogEl;
  const form = dlg.querySelector("form");
  // N16: an empty name (or an enter/exit count outside 1-5, once the
  // spinner's own min/max is bypassed by typing) is caught here, with the
  // browser's own inline message, before it ever reaches the server as a
  // raw 422.
  if (!form.checkValidity()) {
    form.reportValidity();
    return;
  }
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
    // api() shows the lock screen for a 401; N16 maps a remaining 422 (a
    // range check `reportValidity()` cannot catch, e.g. radius_meters) to a
    // catalog sentence, and N48 maps a duplicate-name 409 the same way --
    // both before the raw server text is ever shown.
    if (err.message === "Locked") return;
    fields.error.textContent =
      placeValidationMessage(err) || duplicateNameMessage(err, "places.duplicateName") || err.message;
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
  fields.radiusNumber.value = DEFAULT_RADIUS;
  fields.color.value = PLACE_PALETTE[0];
  fields.enter.value = DEFAULT_ENTER_CONFIRMATIONS;
  fields.exit.value = DEFAULT_EXIT_CONFIRMATIONS;
  fields.error.textContent = "";
  if (colorPicker) colorPicker.setValue(PLACE_PALETTE[0]);
  if (locator) locator.reset();
  if (dialogEl) {
    delete dialogEl.dataset.editId;
    delete dialogEl.dataset.mode;
  }
}

/** places.js's purge() hook for the dialog's own state. */
export function purgeDialog() {
  if (activePick) {
    activePick.abort();
    activePick = null;
  }
  removePreviewCircle();
  if (dialogEl && dialogEl.open) dialogEl.close();
  clearDialogFields();
}
