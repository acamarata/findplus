/*
 * Devices dialog: edit one tracker inside its own row (no second dialog).
 *
 * Purpose    : Pressing Edit on a row in the Devices dialog expands that row into
 *              an editor: a name, the 12 palette colours, an icon grid with a
 *              search box and an "Upload your own" button. Save sends
 *              PATCH /api/devices/{id}; Cancel (or Escape) folds the row back.
 * Inputs     : The row element, the device (GET /api/devices shape), the Edit
 *              button (for aria-expanded and focus), and an async `onSaved`.
 * Outputs    : One open editor at a time. `closeInlineEditor()` and
 *              `purgeInlineEditor()` (lock) fold it away and destroy both pickers,
 *              their "Your icons" thumbnails included (PROMPT.md invariant 11).
 * Constraints: createElement/textContent only. Tracking stays on the row's own
 *              checkbox, so this editor sends label, icon and colour and nothing
 *              else. The wizard still uses devices_dialog.js (no Devices dialog
 *              there). Escape closes the editor, not the whole Devices dialog.
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";
import { displayName } from "./state.js";
import { createIconPicker } from "./components/icon-picker.js";
import { createColorPicker } from "./components/color-picker.js";

const DEFAULT_ICON = "letter";
const DEFAULT_COLOR = "#4f8cf7";

/** The one open editor: { row, node, button, icon, color, pickers }, or null. */
let open = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function group(legend, className) {
  const box = el("fieldset", `fp-dialog-group ${className}`);
  box.appendChild(el("legend", "", legend));
  return box;
}

function nameField() {
  const wrap = el("div", "fp-dialog-field");
  const input = el("input");
  input.id = "fp-device-inline-label";
  input.type = "text";
  input.maxLength = 40;
  const label = el("label", "", t("devices.field.label"));
  label.htmlFor = input.id;
  wrap.append(label, input);
  return { wrap, input };
}

function button(text, className, onClick) {
  const btn = el("button", className, text);
  btn.type = "button";
  btn.addEventListener("click", onClick);
  return btn;
}

/** Fold the editor away and destroy its pickers. */
export function closeInlineEditor({ refocus = false } = {}) {
  if (!open) return;
  const { row, node, button: edit, pickers } = open;
  open = null;
  pickers.forEach((p) => p.destroy());
  node.remove();
  row.classList.remove("is-editing");
  edit.setAttribute("aria-expanded", "false");
  if (refocus) edit.focus();
}

/** Lock purge: nothing the editor held may stay in the page. */
export function purgeInlineEditor() {
  closeInlineEditor();
}

async function save(state, input, error, onSaved) {
  const body = { label: input.value.trim(), icon: state.icon, color: state.color };
  try {
    await api(`/api/devices/${encodeURIComponent(state.id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    closeInlineEditor();
    await onSaved(state.id);
  } catch (err) {
    // api() shows the lock screen for a 401; anything else (404, 422) lands here.
    if (err.message !== "Locked") error.textContent = err.message;
  }
}

function buildEditor(device, onSaved) {
  const state = { id: device.device_id, icon: device.icon || DEFAULT_ICON, color: device.color || DEFAULT_COLOR };
  const node = el("div", "device-edit");
  // What Save will send, readable from the DOM (a stable hook for tests and scripts).
  const sync = () => { node.dataset.icon = state.icon; node.dataset.color = state.color; };
  sync();
  node.setAttribute("role", "group");
  node.setAttribute("aria-label", t("devices.dialog.title_edit", { name: displayName(device) }));
  const name = nameField();
  name.input.value = device.label || "";
  const colorBox = group(t("devices.field.color"), "device-edit-color");
  const iconBox = group(t("devices.field.icon"), "device-edit-icon");
  const error = el("p", "fp-dialog-error");
  error.setAttribute("role", "alert");
  const color = createColorPicker(colorBox, {
    value: state.color, allowCustom: false, onChange: (hex) => { state.color = hex; sync(); },
  });
  const icon = createIconPicker(iconBox, {
    value: state.icon, search: true, letterLabel: t("devices.field.letter"), onChange: (id) => { state.icon = id; sync(); },
  });
  const actions = el("div", "device-edit-actions");
  actions.append(
    button(t("devices.inline.save"), "btn", () => save(state, name.input, error, onSaved)),
    button(t("common.cancel"), "btn-secondary", () => closeInlineEditor({ refocus: true })),
  );
  node.append(name.wrap, colorBox, iconBox, error, actions);
  name.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); save(state, name.input, error, onSaved); }
  });
  node.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    e.stopPropagation();
    closeInlineEditor({ refocus: true });
  });
  return { node, name, pickers: [color, icon] };
}

/**
 * Expand `row` into the editor, or fold it back if it is already open.
 * Opening a second row folds the first (its unsaved changes are dropped).
 */
export function toggleInlineEditor(row, device, editButton, onSaved) {
  const wasThis = open && open.row === row;
  closeInlineEditor();
  if (wasThis) return;
  const built = buildEditor(device, onSaved);
  row.append(built.node);
  row.classList.add("is-editing");
  editButton.setAttribute("aria-expanded", "true");
  open = { row, node: built.node, button: editButton, pickers: built.pickers };
  row.scrollIntoView({ block: "start" });
  built.name.input.focus();
}
