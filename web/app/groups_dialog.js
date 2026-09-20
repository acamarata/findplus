/*
 * Groups tab: the add/edit dialog for one group.
 *
 * Purpose    : Drive the reused <dialog> that creates or edits a group — name,
 *              icon, colour, quorum, cluster radius, stale-after minutes and
 *              the tracked-device member checklist.
 * Inputs     : GET /api/devices for the member rows; the group object handed in
 *              per call by groups_list.js, which owns the card registry.
 * Outputs    : POST /api/groups, PUT /api/groups/{id} and
 *              PUT /api/groups/{id}/members on save.
 * Constraints: The dialog's elements are built by groups_dialog_dom.js, never
 *              from raw markup, and every badge through components/badge.js.
 *              Every static string comes from the catalog through t().
 *              initDialog()'s onSaved callback is the only way this module
 *              talks back to groups.js, so the dependency runs one way.
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";
import { createIconPicker } from "./components/icon-picker.js";
import { createColorPicker } from "./components/color-picker.js";
import { buildDialog, memberRow, renderIconPreview, renderColorPreview } from "./groups_dialog_dom.js";

const DEFAULT_ICON = "lucide:users";
const DEFAULT_COLOR = "#27ae60";
const DEFAULT_QUORUM = "majority";
const DEFAULT_RADIUS = "150";
const DEFAULT_STALE = "90";

let onSaved = null;
let dialogEl = null;
let fields = null;
let iconPicker = null;
let colorPicker = null;

/** Called once by groups.js's init() before any dialog function is used. */
export function initDialog(onSavedArg) {
  onSaved = onSavedArg;
}

function togglePopover(host, other) {
  other.hidden = true;
  host.hidden = !host.hidden;
}

/** Both preview buttons: an icon or colour pick invalidates both (the icon
 * badge is drawn with the current colour too, per renderIconPreview). */
function renderPreviews() {
  renderIconPreview(fields);
  renderColorPreview(fields);
}

/** The pickers are destroyed by a purge and rebuilt here; the buttons are not. */
function ensurePickers() {
  if (iconPicker) return;
  iconPicker = createIconPicker(fields.iconHost, {
    value: fields.icon.value,
    onChange: (id) => {
      fields.icon.value = id;
      renderPreviews();
      fields.iconHost.hidden = true;
    },
  });
  colorPicker = createColorPicker(fields.colorHost, {
    value: fields.color.value,
    onChange: (hex) => {
      fields.color.value = hex;
      renderPreviews();
      fields.colorHost.hidden = true;
    },
  });
}

function wireDialog(dlg) {
  fields.iconBtn.addEventListener("click", () => togglePopover(fields.iconHost, fields.colorHost));
  fields.colorBtn.addEventListener("click", () => togglePopover(fields.colorHost, fields.iconHost));
  fields.radius.addEventListener("input", () => {
    fields.radiusOut.textContent = fields.radius.value;
  });
  fields.quorum.addEventListener("change", () => {
    fields.quorumN.hidden = fields.quorum.value !== "custom";
  });
  // A bare "letter" icon draws its glyph from the name (CR-C-E5 F7): keep the
  // preview live as the user types instead of only on icon/colour pick.
  fields.name.addEventListener("input", () => renderIconPreview(fields));
  // Esc with a popover open closes the popover, not the whole dialog.
  dlg.addEventListener("cancel", (e) => {
    if (fields.iconHost.hidden && fields.colorHost.hidden) return;
    e.preventDefault();
    fields.iconHost.hidden = true;
    fields.colorHost.hidden = true;
  });
}

function ensureDialog() {
  if (dialogEl) return dialogEl;
  const built = buildDialog({ onSave, onCancel });
  dialogEl = built.dlg;
  fields = built.fields;
  document.body.appendChild(dialogEl);
  wireDialog(dialogEl);
  renderPreviews();
  return dialogEl;
}

function clearMembers() {
  const box = fields.members;
  while (box.lastChild && box.lastChild !== fields.membersLegend) box.removeChild(box.lastChild);
}

/** Untracked devices cannot report presence, so they are not offered. */
async function populateMembers() {
  const { devices } = await api("/api/devices");
  clearMembers();
  devices.filter((d) => d.is_tracked).forEach((d) => fields.members.appendChild(memberRow(d)));
}

function applyQuorum(quorum) {
  if (/^\d+$/.test(String(quorum))) {
    fields.quorum.value = "custom";
    fields.quorumN.value = String(quorum);
    fields.quorumN.hidden = false;
    return;
  }
  fields.quorum.value = quorum;
  fields.quorumN.hidden = true;
}

function applyGroup(group) {
  fields.name.value = group ? group.name : "";
  fields.icon.value = (group && group.icon) || DEFAULT_ICON;
  fields.color.value = (group && group.color) || DEFAULT_COLOR;
  iconPicker.setValue(fields.icon.value);
  colorPicker.setValue(fields.color.value);
  renderPreviews();
  applyQuorum(group ? group.quorum : DEFAULT_QUORUM);
  const radius = group ? String(group.cluster_radius_meters) : DEFAULT_RADIUS;
  fields.radius.value = radius;
  fields.radiusOut.textContent = radius;
  fields.stale.value = group ? String(group.stale_after_minutes) : DEFAULT_STALE;
  const ids = new Set(((group && group.members) || []).map((m) => m.device_id));
  fields.members.querySelectorAll("input[data-device-id]").forEach((box) => {
    box.checked = ids.has(box.dataset.deviceId);
  });
}

async function fillDialog(mode, id, group) {
  const dlg = ensureDialog();
  ensurePickers();
  dlg.dataset.mode = mode;
  if (mode === "edit") dlg.dataset.editId = String(id);
  else delete dlg.dataset.editId;
  fields.title.textContent = mode === "edit" ? t("groups.dialog.title_edit") : t("groups.dialog.title_add");
  fields.error.textContent = "";
  // The member rows are fetched before anything is ticked: applyGroup would
  // otherwise look for checkboxes that do not exist yet. A 401 here means the
  // lock screen has taken the page, so there is nothing left to open; any
  // other failure still opens the dialog, with the reason in it and an empty
  // member list, rather than rejecting into nothing.
  try {
    await populateMembers();
  } catch (err) {
    if (err.message === "Locked") return;
    fields.error.textContent = err.message;
  }
  applyGroup(group);
  dlg.showModal();
  fields.name.focus();
}

/**
 * fillDialog() is async (it awaits ensurePickers()/populateMembers()); an
 * unhandled rejection here reads as a click that silently does nothing and
 * trips test_no_javascript_errors (CR-C-E5 F6). populateMembers()'s own
 * failures already land in fields.error; this is the backstop for anything
 * earlier in fillDialog, surfaced the same way when the dialog exists.
 */
function reportFillFailure(err) {
  if (fields) fields.error.textContent = err.message;
}

export function showAddDialog() {
  fillDialog("add", null, null).catch(reportFillFailure);
}

/** groups_list.js looks the group up (it owns the card registry) and hands it here. */
export function openEditDialog(id, group) {
  fillDialog("edit", id, group).catch(reportFillFailure);
}

function groupBody() {
  return {
    name: fields.name.value.trim(),
    icon: fields.icon.value,
    color: fields.color.value,
    quorum: fields.quorum.value === "custom" ? String(fields.quorumN.value) : fields.quorum.value,
    cluster_radius_meters: Number(fields.radius.value),
    stale_after_minutes: Number(fields.stale.value),
    member_ids: [...fields.members.querySelectorAll("input:checked")].map((c) => c.dataset.deviceId),
  };
}

function jsonOpts(method, body) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/**
 * Save, as one call on add and two on edit.
 *
 * GroupUpdate carries no member_ids and set_members carries nothing else, so an
 * edit is a PUT of the group followed by a PUT of its membership. The second
 * only runs if the first succeeded: a half-applied save with the error still on
 * screen beats silently writing one of the two.
 */
async function saveGroup(body) {
  if (dialogEl.dataset.mode !== "edit") {
    await api("/api/groups", jsonOpts("POST", body));
    return;
  }
  const id = dialogEl.dataset.editId;
  const { member_ids: memberIds, ...groupFields } = body;
  await api(`/api/groups/${id}`, jsonOpts("PUT", groupFields));
  await api(`/api/groups/${id}/members`, jsonOpts("PUT", { member_ids: memberIds }));
}

function handleSaveError(err) {
  // api() shows the lock screen for a 401; anything else belongs in the dialog.
  if (err.message === "Locked") return;
  if (err.message.includes("not found")) {
    // Another tab deleted the group mid-edit: resync instead of arguing.
    dialogEl.close();
    if (onSaved) onSaved();
    return;
  }
  fields.error.textContent = err.message;
  if (err.message.includes("already exists")) fields.name.focus();
}

async function onSave() {
  // The Save button is type="button", so the input's `required` never fires:
  // this check is the only thing between a blank name and a 422.
  if (!fields.name.value.trim()) {
    fields.error.textContent = t("groups.error.name_required");
    return;
  }
  try {
    await saveGroup(groupBody());
    dialogEl.close();
    if (onSaved) await onSaved();
  } catch (err) {
    handleSaveError(err);
  }
}

function onCancel() {
  dialogEl.close();
}

function clearDialogFields() {
  if (!fields) return;
  fields.name.value = "";
  fields.icon.value = DEFAULT_ICON;
  fields.color.value = DEFAULT_COLOR;
  fields.quorum.value = DEFAULT_QUORUM;
  fields.quorumN.value = "";
  fields.quorumN.hidden = true;
  fields.radius.value = DEFAULT_RADIUS;
  fields.radiusOut.textContent = DEFAULT_RADIUS;
  fields.stale.value = DEFAULT_STALE;
  fields.error.textContent = "";
  clearMembers();
  delete dialogEl.dataset.editId;
  delete dialogEl.dataset.mode;
}

/**
 * groups.js's purge() hook.
 *
 * Closing the dialog only stops it being displayed. The name, the member rows
 * (real device names) and both pickers' DOM survive, readable from DevTools
 * behind the lock screen, which is what PROMPT.md §2 invariant 11 forbids. The
 * pickers are destroyed rather than blanked and rebuilt on the next open; the
 * emptied <dialog> element stays in the page so reopening never creates a
 * second #fp-group-dialog.
 */
export function purgeDialog() {
  if (!dialogEl) return;
  if (dialogEl.open) dialogEl.close();
  if (iconPicker) iconPicker.destroy();
  if (colorPicker) colorPicker.destroy();
  iconPicker = null;
  colorPicker = null;
  clearDialogFields();
}
