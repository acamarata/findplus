/*
 * The person editor: Edit person on the Person page and on a person's card.
 *
 * Purpose    : A person is not a group, so its editor has none of a group's
 *              alert-rule fields. It asks for a name, person or pet, an icon
 *              and colour, and which trackers belong to them, each with a role
 *              and how much to trust it.
 * Inputs     : A person id, and `onSaved()` to run after a save.
 * Outputs    : PATCH /api/people/{id}, PUT /api/people/{id}/members and
 *              PUT /api/people/trackers/{device_id} (only for changed rows).
 * Constraints: createElement/textContent only; the dialog is built once, filled
 *              per open and emptied by purgePersonEditor() on lock. Esc with a
 *              picker open closes the picker, not the dialog.
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";
import { createIconPicker } from "./components/icon-picker.js";
import { createColorPicker, DEVICE_PALETTE } from "./components/color-picker.js";
import { pickerRow, renderIconPreview, renderColorPreview } from "./groups_dialog_dom.js";
import { labeled } from "./groups_dialog_fields.js";
import { buildMembers } from "./person_editor_members.js";
import { saveTracker } from "./person_api.js";
import { duplicateNameMessage } from "./dialog_errors.js";

const JSON_HEADERS = { "Content-Type": "application/json" };
const send = (method, path, body) => api(path, { method, headers: JSON_HEADERS, body: JSON.stringify(body) });

let dlg = null;
let ui = null;
let members = null;
let current = null;
let saved = null;

function btn(text, cls, onClick) {
  const b = document.createElement("button");
  b.type = "button"; b.className = cls; b.textContent = text;
  b.addEventListener("click", onClick);
  return b;
}

function kindRadios() {
  const set = document.createElement("fieldset");
  set.className = "pe-kind";
  const legend = document.createElement("legend");
  legend.textContent = t("person.edit.kind");
  set.appendChild(legend);
  const inputs = {};
  ["person", "pet"].forEach((kind) => {
    const label = document.createElement("label");
    label.className = "fp-member-row";
    const input = document.createElement("input");
    input.type = "radio"; input.name = "pe-kind"; input.value = kind;
    inputs[kind] = input;
    label.append(input, document.createTextNode(t(`person.kind.${kind}`)));
    set.appendChild(label);
  });
  return { set, inputs };
}

function togglePopover(host, other) {
  other.hidden = true;
  host.hidden = !host.hidden;
}

function build() {
  const d = document.createElement("dialog");
  d.id = "fp-person-dialog";
  d.setAttribute("aria-labelledby", "fp-person-dialog-title");
  const form = document.createElement("form");
  form.method = "dialog";
  const title = document.createElement("h2");
  title.id = "fp-person-dialog-title";
  const name = document.createElement("input");
  name.type = "text"; name.id = "fp-person-name"; name.maxLength = 40; name.required = true;
  const icon = document.createElement("input"); icon.type = "hidden";
  const color = document.createElement("input"); color.type = "hidden";
  const iconRow = pickerRow("fp-person-icon", t("groups.field.icon"), icon, "fp-icon-swatch");
  const colorRow = pickerRow("fp-person-color", t("groups.field.color"), color, "fp-color-swatch");
  const kind = kindRadios();
  const holder = document.createElement("div");
  const error = document.createElement("p");
  error.className = "fp-dialog-error"; error.id = "fp-person-error"; error.setAttribute("role", "alert");
  const footer = document.createElement("footer");
  footer.append(btn(t("common.save"), "btn", onSave), btn(t("common.cancel"), "btn-secondary", () => d.close()));
  form.append(title, labeled(t("groups.field.name"), name, name.id), kind.set, iconRow.wrap, colorRow.wrap, holder, error, footer);
  d.appendChild(form);
  ui = { title, name, icon, color, iconBtn: iconRow.btn, iconHost: iconRow.host, colorBtn: colorRow.btn, colorHost: colorRow.host, kind: kind.inputs, holder, error, pickers: null };
  iconRow.btn.addEventListener("click", () => togglePopover(ui.iconHost, ui.colorHost));
  colorRow.btn.addEventListener("click", () => togglePopover(ui.colorHost, ui.iconHost));
  name.addEventListener("input", () => renderIconPreview(ui));
  d.addEventListener("cancel", (e) => {
    if (ui.iconHost.hidden && ui.colorHost.hidden) return;
    e.preventDefault();
    ui.iconHost.hidden = true; ui.colorHost.hidden = true;
  });
  document.body.appendChild(d);
  return d;
}

function mountPickers() {
  const preview = () => { renderIconPreview(ui); renderColorPreview(ui); };
  ui.pickers = {
    icon: createIconPicker(ui.iconHost, { value: ui.icon.value, onChange: (id) => { ui.icon.value = id; preview(); ui.iconHost.hidden = true; } }),
    color: createColorPicker(ui.colorHost, { value: ui.color.value, onChange: (hex) => { ui.color.value = hex; preview(); ui.colorHost.hidden = true; } }),
  };
}

function fill(person, devices, people) {
  ui.title.textContent = person.id ? t("person.edit.title", { name: person.name }) : t("person.edit.createTitle");
  ui.name.value = person.name;
  ui.icon.value = person.icon || "lucide:user";
  ui.color.value = person.color || "#27ae60";
  ui.kind[person.kind === "pet" ? "pet" : "person"].checked = true;
  if (!ui.pickers) mountPickers();
  ui.pickers.icon.setValue(ui.icon.value);
  ui.pickers.color.setValue(ui.color.value);
  renderIconPreview(ui);
  renderColorPreview(ui);
  ui.error.textContent = "";
  members = buildMembers(devices, people, person);
  ui.holder.replaceChildren(members.fieldset);
}

async function createAll(picked) {
  const kind = ui.kind.pet.checked ? "pet" : "person";
  const roles = Object.fromEntries(picked.map((x) => [x.device_id, x.role]));
  await send("POST", "/api/people", { name: ui.name.value.trim(), kind, color: ui.color.value, icon: ui.icon.value, member_ids: picked.map((x) => x.device_id), roles });
  for (const x of picked.filter((p) => p.carry_weight != null)) await saveTracker(x.device_id, { role: x.role, carry_weight: x.carry_weight });
}

async function writeAll(picked) {
  if (!current.id) return createAll(picked);
  const id = current.id;
  const kind = ui.kind.pet.checked ? "pet" : "person";
  await send("PATCH", `/api/people/${id}`, { name: ui.name.value.trim(), kind, color: ui.color.value, icon: ui.icon.value });
  const before = current.trackers.map((x) => x.device_id).sort().join();
  if (picked.map((x) => x.device_id).sort().join() !== before) await send("PUT", `/api/people/${id}/members`, { member_ids: picked.map((x) => x.device_id) });
  for (const x of picked.filter((p) => p.changed)) await saveTracker(x.device_id, { role: x.role, carry_weight: x.carry_weight });
}

async function onSave() {
  const picked = members.collect();
  if (!ui.name.value.trim()) { ui.error.textContent = t("groups.error.name_required"); ui.name.focus(); return; }
  if (!picked.length) { ui.error.textContent = t("person.edit.needOne"); return; }
  try {
    await writeAll(picked);
    dlg.close();
    if (saved) await saved();
  } catch (err) {
    if (err.message === "Locked") return;
    ui.error.textContent = duplicateNameMessage(err, "groups.error.duplicate_name", ui.name.value.trim()) || err.message;
  }
}

/** Open the editor for person `id`; `onSaved` runs after a successful save. */
export async function openPersonEditor(id, onSaved) {
  saved = onSaved || null;
  try {
    const [person, devices, people] = await Promise.all([api(`/api/people/${id}`), api("/api/devices"), api("/api/people")]);
    current = person;
    if (!dlg) dlg = build();
    fill(person, devices.devices || [], people);
    dlg.showModal();
    ui.name.focus();
  } catch (err) {
    if (err.message !== "Locked") throw err;
  }
}

/** Palette colour no person uses yet (the first one when all twelve are taken). */
function unusedColor(people) {
  const used = new Set(people.map((p) => (p.color || "").toLowerCase()));
  return DEVICE_PALETTE.find((c) => !used.has(c)) || DEVICE_PALETTE[0];
}

/**
 * Open the editor empty, to add a person or pet (the app bar's Add > Person).
 * The new person starts with the first palette colour no one has; `onSaved`
 * runs after the POST succeeds.
 */
export async function openPersonCreate(onSaved) {
  saved = onSaved || null;
  try {
    const [devices, people] = await Promise.all([api("/api/devices"), api("/api/people")]);
    current = { id: null, name: "", kind: "person", icon: "lucide:user", color: unusedColor(people), trackers: [] };
    if (!dlg) dlg = build();
    fill(current, devices.devices || [], people);
    dlg.showModal();
    ui.name.focus();
  } catch (err) {
    if (err.message !== "Locked") throw err;
  }
}

/** Lock purge: no name or tracker may stay in the page. */
export function purgePersonEditor() {
  if (!dlg) return;
  if (dlg.open) dlg.close();
  if (ui.pickers) { ui.pickers.icon.destroy(); ui.pickers.color.destroy(); ui.pickers = null; }
  ui.name.value = ""; ui.error.textContent = ""; ui.holder.replaceChildren(); ui.title.textContent = "";
  current = null; members = null;
}
