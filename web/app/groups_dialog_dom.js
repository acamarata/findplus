/*
 * Group dialog: element construction.
 *
 * Purpose    : Build the <dialog> the group add/edit flow drives, and the two
 *              small pieces it rebuilds as data arrives (the icon-button
 *              preview and one member row). Split out of groups_dialog.js at
 *              the PRI rule-7 300-line file cap, the same way provider_chrome.js
 *              came out of devices.js.
 * Inputs     : The save and cancel handlers groups_dialog.js owns; one device
 *              row from GET /api/devices for memberRow().
 * Outputs    : { dlg, fields } — the dialog element and every input in it by
 *              name, so the caller never queries the DOM to read a field.
 * Constraints: Pure construction, no network, no module state. Every element is
 *              built with createElement/textContent, never raw markup, and
 *              every static string comes from the catalog through t().
 */
"use strict";

import { t } from "./i18n.js";
import { renderBadge } from "./components/badge.js";

const DEFAULT_ICON = "lucide:users";
const DEFAULT_COLOR = "#27ae60";
const DEFAULT_RADIUS = "150";
const DEFAULT_STALE = "90";

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

function popoverHost(id) {
  const host = document.createElement("div");
  host.className = "fp-popover";
  host.id = id;
  host.hidden = true;
  // Esc inside a popover closes the popover only. The dialog's own "cancel"
  // handler does the holding back: a UA closes <dialog> as the keydown's
  // default action, which stopPropagation alone never reaches.
  host.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    e.stopPropagation();
    host.hidden = true;
  });
  return host;
}

function pickerRow(id, ariaLabel, hiddenInput) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = `${id}-btn`;
  btn.setAttribute("aria-label", ariaLabel);
  const host = popoverHost(`${id}-popover`);
  const wrap = document.createElement("div");
  wrap.className = "fp-picker-row";
  wrap.append(btn, hiddenInput, host);
  return { btn, host, wrap };
}

function quorumRow() {
  const select = document.createElement("select");
  select.id = "fp-group-quorum";
  for (const value of ["any", "majority", "all", "custom"]) {
    const opt = document.createElement("option");
    opt.value = value;
    // any/majority/all are validation.py's own grammar values, not prose; the
    // catalog pins a key for "custom" alone (specs/groups-ui.md § i18n keys).
    opt.textContent = value === "custom" ? t("groups.field.quorum_custom") : value;
    select.appendChild(opt);
  }
  const n = field("number", { id: "fp-group-quorum-n", min: "1", max: "20", value: "2", hidden: true });
  const wrap = document.createElement("div");
  wrap.append(labeled(t("groups.field.quorum"), select), n);
  return { select, n, wrap };
}

function radiusRow() {
  const input = field("range", {
    id: "fp-group-radius", min: "25", max: "2000", step: "25", value: DEFAULT_RADIUS,
  });
  const out = document.createElement("output");
  out.textContent = input.value;
  const wrap = document.createElement("label");
  wrap.textContent = t("groups.field.radius");
  wrap.append(input, out);
  return { input, out, wrap };
}

function staleRow() {
  const input = field("number", { id: "fp-group-stale", min: "10", max: "1440", value: DEFAULT_STALE });
  const hint = document.createElement("p");
  hint.className = "fp-field-hint";
  // honesty.PRESENCE_STALE, verbatim: a stale tag is not a tag left behind.
  hint.textContent = t("groups.field.stale_hint");
  const wrap = document.createElement("div");
  wrap.append(labeled(t("groups.field.stale"), input), hint);
  return { input, wrap };
}

function membersFieldset() {
  const fieldset = document.createElement("fieldset");
  fieldset.id = "fp-group-members";
  const legend = document.createElement("legend");
  legend.textContent = t("groups.field.members");
  fieldset.appendChild(legend);
  return { fieldset, legend };
}

/** One tracked device: its checkbox, its badge and its name. */
export function memberRow(device) {
  const row = document.createElement("label");
  row.className = "fp-member-row";
  const box = field("checkbox", {});
  box.dataset.deviceId = device.device_id;
  const badge = document.createElement("span");
  badge.appendChild(
    renderBadge({
      icon: device.icon, color: device.color, label: device.label, name: device.name, size: 16,
    }),
  );
  const name = document.createElement("span");
  name.textContent = device.name;
  row.append(box, badge, name);
  return row;
}

/** The icon button shows the badge the group will actually be drawn with. */
export function renderIconPreview(fields) {
  const btn = fields.iconBtn;
  while (btn.firstChild) btn.removeChild(btn.firstChild);
  btn.appendChild(
    renderBadge({
      icon: fields.icon.value,
      color: fields.color.value,
      label: null,
      name: fields.name.value || "?",
      size: 20,
    }),
  );
}

export function buildDialog({ onSave, onCancel }) {
  const dlg = document.createElement("dialog");
  dlg.id = "fp-group-dialog";
  // Native <dialog> exposes the role but not a name; without this a screen
  // reader announces "dialog" and nothing else (devices_dialog.js:96 does the
  // same for its own editor).
  dlg.setAttribute("aria-labelledby", "fp-group-dialog-title");
  const form = document.createElement("form");
  form.method = "dialog";

  const title = document.createElement("h2");
  title.id = "fp-group-dialog-title";
  const name = field("text", { id: "fp-group-name", required: true, maxLength: 40 });
  const iconValue = field("hidden", { id: "fp-group-icon", value: DEFAULT_ICON });
  const colorValue = field("hidden", { id: "fp-group-color", value: DEFAULT_COLOR });
  const icon = pickerRow("fp-group-icon", t("groups.field.icon"), iconValue);
  const color = pickerRow("fp-group-color", t("groups.field.color"), colorValue);
  const quorum = quorumRow();
  const radius = radiusRow();
  const stale = staleRow();
  const members = membersFieldset();

  const error = document.createElement("p");
  error.className = "fp-dialog-error";
  error.id = "fp-group-dialog-error";
  const footer = document.createElement("footer");
  footer.append(button(t("common.save"), onSave), button(t("common.cancel"), onCancel));

  form.append(
    title, labeled(t("groups.field.name"), name), icon.wrap, color.wrap,
    quorum.wrap, radius.wrap, stale.wrap, members.fieldset, error, footer,
  );
  dlg.appendChild(form);

  const fields = {
    title, name, error,
    icon: iconValue, iconBtn: icon.btn, iconHost: icon.host,
    color: colorValue, colorBtn: color.btn, colorHost: color.host,
    quorum: quorum.select, quorumN: quorum.n,
    radius: radius.input, radiusOut: radius.out,
    stale: stale.input, members: members.fieldset, membersLegend: members.legend,
  };
  return { dlg, fields };
}
