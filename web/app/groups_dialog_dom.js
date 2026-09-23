/*
 * Group dialog: element construction.
 *
 * Purpose    : Build the <dialog> the group add/edit flow drives, and the two
 *              small pieces it rebuilds as data arrives (the icon-button
 *              preview and one member row). Split out of groups_dialog.js at
 *              the PRI rule-7 300-line file cap, the same way provider_chrome.js
 *              came out of devices.js; the quorum/radius/stale/members row
 *              builders live in groups_dialog_fields.js (same cap, E13 loop-1).
 * Inputs     : The save and cancel handlers groups_dialog.js owns; one device
 *              row from GET /api/devices for memberRow().
 * Outputs    : { dlg, fields } — the dialog element and every input in it by
 *              name, so the caller never queries the DOM to read a field.
 *              pickerRow()/renderIconPreview()/renderColorPreview()/
 *              closeOpenPopover()/clampPopoverToViewport() are also exported for
 *              setup_steps/groups.js's wizard icon/colour triggers (R-P2-28.2).
 * Constraints: Pure construction, no network, no module state. Every element is
 *              built with createElement/textContent, never raw markup, and
 *              every static string comes from the catalog through t().
 */
"use strict";

import { t } from "./i18n.js";
import { displayName } from "./state.js";
import { renderBadge } from "./components/badge.js";
import { field, labeled, quorumRow, radiusRow, staleRow, membersFieldset } from "./groups_dialog_fields.js";

const DEFAULT_ICON = "lucide:users";
const DEFAULT_COLOR = "#27ae60";

function button(text, onClick, className) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = text;
  if (className) btn.className = className;
  btn.addEventListener("click", onClick);
  return btn;
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

/**
 * A picker trigger row: a visible label, then the button that opens the
 * popover. `swatchClass` reuses icon-picker.js's/color-picker.js's own swatch
 * styling instead of a bare unstyled `<button>` (visual gate W3 finding 1).
 */
export function pickerRow(id, labelText, hiddenInput, swatchClass) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = `${id}-btn`;
  btn.className = swatchClass;
  btn.setAttribute("aria-label", labelText);
  const label = document.createElement("span");
  label.className = "fp-picker-label";
  label.textContent = labelText;
  const host = popoverHost(`${id}-popover`);
  const control = document.createElement("div");
  control.className = "fp-picker-control";
  control.append(btn, hiddenInput, host);
  const wrap = document.createElement("div");
  wrap.className = "fp-picker-row";
  wrap.append(label, control);
  return { btn, host, wrap };
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
  // UAT U6: the group dialog's own member picker shows the label too.
  name.textContent = displayName(device);
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

/**
 * The colour button previews the picked swatch as its own background, the
 * same way icon-picker.js's/color-picker.js's own swatches show colour —
 * without this the closed button had no content at all (visual gate W3
 * finding 1: "the colour picker is absent").
 */
export function renderColorPreview(fields) {
  fields.colorBtn.style.background = fields.color.value;
}

/** Closes whichever picker popover is open and returns focus to its own
 * trigger — the outside-click/Escape paths (visual gate W3 round 2). The
 * "click the trigger again" close never needs this: focus is already there. */
export function closeOpenPopover(fields) {
  if (!fields.iconHost.hidden) {
    fields.iconHost.hidden = true;
    fields.iconBtn.focus();
  }
  if (!fields.colorHost.hidden) {
    fields.colorHost.hidden = true;
    fields.colorBtn.focus();
  }
}

/**
 * Keeps an open popover inside the viewport AND inside its dialog.
 *
 * It opens anchored to its trigger (`left: 0` of `.fp-picker-control`, the
 * popover's positioned ancestor), which is correct near the dialog's left
 * edge but not for a trigger further right: a 320px-wide panel anchored
 * there can run past the dialog's own right edge (a 420px-wide dialog still
 * well inside a 1280px viewport) or, on a narrow dialog, past the viewport's
 * right edge too -- both are visual gate W3 round 2 findings, so both edges
 * are checked and the tighter one wins.
 */
export function clampPopoverToViewport(host) {
  if (host.hidden) return;
  host.style.left = "0";
  const dlg = host.closest("dialog");
  const viewportLimit = document.documentElement.clientWidth - 16;
  const dialogLimit = dlg ? dlg.getBoundingClientRect().right - 1 : viewportLimit;
  const overflow = host.getBoundingClientRect().right - Math.min(viewportLimit, dialogLimit);
  if (overflow > 0) host.style.left = `-${overflow}px`;
}

/** A click outside both the open popover's host and its own trigger closes
 * it (the trigger's own click is togglePopover's job, in groups_dialog.js). */
export function closePopoverIfOutside(fields, target) {
  const outsideIcon = !target.closest("#fp-group-icon-popover, #fp-group-icon-btn");
  const outsideColor = !target.closest("#fp-group-color-popover, #fp-group-color-btn");
  if ((!fields.iconHost.hidden && outsideIcon) || (!fields.colorHost.hidden && outsideColor)) {
    closeOpenPopover(fields);
  }
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
  const icon = pickerRow("fp-group-icon", t("groups.field.icon"), iconValue, "fp-icon-swatch");
  const color = pickerRow("fp-group-color", t("groups.field.color"), colorValue, "fp-color-swatch");
  const quorum = quorumRow();
  const radius = radiusRow();
  const stale = staleRow();
  const members = membersFieldset();

  const error = document.createElement("p");
  error.className = "fp-dialog-error";
  error.id = "fp-group-dialog-error";
  const footer = document.createElement("footer");
  footer.append(button(t("common.save"), onSave, "btn"), button(t("common.cancel"), onCancel, "btn-secondary"));

  form.append(
    title, labeled(t("groups.field.name"), name, name.id), icon.wrap, color.wrap,
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
