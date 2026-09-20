/*
 * Device edit dialog: one device's label, icon, colour and tracked flag.
 *
 * Purpose    : Build and drive the reused <dialog> that edits one device, and
 *              send the result as PATCH /api/devices/{device_id}.
 * Inputs     : A device row (the shape GET /api/devices returns) handed in per
 *              call; devices.js owns the device cache.
 * Outputs    : PATCH /api/devices/{device_id} on save, then the `onSaved`
 *              callback initDialog() was given.
 * Constraints: Edit only. Devices come from a provider, so there is no add
 *              form here, unlike places_dialog.js. Every element is built with
 *              createElement/textContent, never raw markup. The pickers report
 *              through their own onChange callback and nothing else — no DOM
 *              CustomEvents (specs/labels-and-icons.md § UI components).
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";
import { createIconPicker } from "./components/icon-picker.js";
import { createColorPicker } from "./components/color-picker.js";

const DEFAULT_ICON = "letter";
const DEFAULT_COLOR = "#4f8cf7";

let dialogEl = null;
let fields = null;
let iconPicker = null;
let colorPicker = null;
let onSaved = null;

/** A labelled fieldset around a picker, so the swatch grid has a group name. */
function pickerGroup(legendText) {
  const group = document.createElement("fieldset");
  group.className = "fp-dialog-group";
  const legend = document.createElement("legend");
  legend.textContent = legendText;
  group.appendChild(legend);
  return group;
}

function labeled(text, input, id) {
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = text;
  const wrap = document.createElement("div");
  wrap.className = "fp-dialog-field";
  wrap.append(label, input);
  return wrap;
}

function button(text, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = text;
  btn.addEventListener("click", onClick);
  return btn;
}

/** The label, tracked and hidden icon/colour inputs, built once. */
function buildFields() {
  const label = document.createElement("input");
  label.id = "fp-device-label";
  label.type = "text";
  label.maxLength = 40;
  const tracked = document.createElement("input");
  tracked.id = "fp-device-tracked";
  tracked.type = "checkbox";
  const icon = document.createElement("input");
  icon.type = "hidden";
  icon.id = "fp-device-icon";
  const color = document.createElement("input");
  color.type = "hidden";
  color.id = "fp-device-color";
  const error = document.createElement("p");
  error.className = "fp-dialog-error";
  error.id = "fp-device-dialog-error";
  const title = document.createElement("h2");
  title.id = "fp-device-dialog-title";
  return { label, tracked, icon, color, error, title };
}

/**
 * Build the dialog on first use.
 *
 * Lazily, not at boot: createIconPicker() reads the <symbol> elements from the
 * sprite main.js fetches at startup, and the picker is built once and cached.
 * Building it before that fetch lands would leave an empty icon grid for the
 * rest of the session.
 */
function ensureDialog() {
  if (dialogEl) return dialogEl;

  const dlg = document.createElement("dialog");
  dlg.id = "fp-device-dialog";
  dlg.setAttribute("aria-labelledby", "fp-device-dialog-title");
  const form = document.createElement("form");
  form.method = "dialog";

  const f = buildFields();
  const iconGroup = pickerGroup(t("devices.field.icon"));
  const colorGroup = pickerGroup(t("devices.field.color"));

  form.append(
    f.title,
    labeled(t("devices.field.label"), f.label, f.label.id),
    f.icon,
    f.color,
    iconGroup,
    colorGroup,
    labeled(t("devices.field.tracked"), f.tracked, f.tracked.id),
    f.error,
  );

  const footer = document.createElement("footer");
  footer.append(button(t("common.save"), onSave), button(t("common.cancel"), () => dlg.close()));
  form.appendChild(footer);
  dlg.appendChild(form);
  document.body.appendChild(dlg);

  fields = f;
  dialogEl = dlg;
  iconPicker = createIconPicker(iconGroup, {
    value: DEFAULT_ICON,
    onChange: (value) => {
      fields.icon.value = value;
    },
    letterLabel: t("devices.field.letter"),
  });
  colorPicker = createColorPicker(colorGroup, {
    value: DEFAULT_COLOR,
    onChange: (value) => {
      fields.color.value = value;
    },
    customLabel: t("devices.field.customColor"),
  });
  return dlg;
}

/**
 * Send the edited fields.
 *
 * `label` always goes, including as "": the route reads it through
 * `model_fields_set`, so an empty string is how a label is cleared
 * (specs/labels-and-icons.md § Validation rules).
 */
async function onSave() {
  const body = {
    label: fields.label.value.trim(),
    icon: fields.icon.value,
    color: fields.color.value,
    tracked: fields.tracked.checked,
  };
  try {
    await api(`/api/devices/${encodeURIComponent(dialogEl.dataset.editId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    dialogEl.close();
    if (onSaved) await onSaved();
  } catch (err) {
    // api() shows the lock screen for a 401; anything else (404, 422) here.
    if (err.message !== "Locked") fields.error.textContent = err.message;
  }
}

/** Called once by devices.js's wireDeviceControls() before any open. */
export function initDialog(onSavedCb) {
  onSaved = onSavedCb;
}

/** devices.js's Edit button hands the row it already holds straight here. */
export function openEditDialog(id, device) {
  const dlg = ensureDialog();
  dlg.dataset.mode = "edit";
  dlg.dataset.editId = String(id);
  fields.title.textContent = t("devices.dialog.title_edit", { name: device.name });
  fields.label.value = device.label || "";
  fields.icon.value = device.icon || DEFAULT_ICON;
  fields.color.value = device.color || DEFAULT_COLOR;
  fields.tracked.checked = Boolean(device.is_tracked);
  iconPicker.setValue(fields.icon.value);
  colorPicker.setValue(fields.color.value);
  fields.error.textContent = "";
  dlg.showModal();
  fields.label.focus();
}

/**
 * Blank the dialog, for lock.js's purgeRenderedData().
 *
 * Closing a <dialog> only stops it being displayed: the label and the device id
 * in `dataset.editId` would still be readable from DevTools behind the lock
 * screen, which is what PROMPT.md §2 invariant 11 forbids.
 */
export function purgeDialog() {
  if (!dialogEl) return;
  if (dialogEl.open) dialogEl.close();
  fields.label.value = "";
  fields.icon.value = "";
  fields.color.value = "";
  fields.tracked.checked = false;
  fields.error.textContent = "";
  fields.title.textContent = "";
  iconPicker.setValue(DEFAULT_ICON);
  colorPicker.setValue(DEFAULT_COLOR);
  delete dialogEl.dataset.editId;
  delete dialogEl.dataset.mode;
}
