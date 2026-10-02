/*
 * The place dialog's "Tell me when anyone arrives or leaves" checkbox.
 *
 * Purpose    : A new place should tell the owner when anyone arrives or leaves,
 *              with no second dialog. The box is ticked by default; the channel
 *              is picked for them when exactly one is connected, offered as a
 *              select when several are, and the box is switched off with a reason
 *              when none is.
 * Inputs     : GET /api/alerts/channels (through alerts_rule_channels.js).
 * Outputs    : buildNotifyField(), fillNotify(), readNotify(); the values end up
 *              in POST /api/places as `notify` and `notify_channels`.
 * Constraints: Shown for a new place only. A failed channel lookup leaves the box
 *              ticked and lets the server choose. Built with createElement and
 *              textContent only.
 */
"use strict";

import { t } from "./i18n.js";
import { channelLabels, connectedChannels } from "./alerts_rule_channels.js";

const ALL = "all";

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** `{wrap, box, line, select, connected}`. */
export function buildNotifyField() {
  const label = el("label", "fp-notify-label");
  const box = el("input");
  box.type = "checkbox";
  box.id = "fp-place-notify";
  box.checked = true;
  label.append(box, el("span", "", t("places.notify.label")));
  const line = el("p", "fp-field-hint fp-notify-line");
  line.id = "fp-place-notify-line";
  const pickLabel = el("label", "", t("places.notify.pick"));
  const select = el("select");
  select.id = "fp-place-notify-channel";
  pickLabel.htmlFor = select.id;
  const pick = el("div", "fp-dialog-field fp-notify-pick");
  pick.hidden = true;
  pick.append(pickLabel, select);
  const wrap = el("div", "fp-notify");
  wrap.append(label, line, pick);
  box.setAttribute("aria-describedby", line.id);
  return { wrap, box, line, select, pick, connected: null };
}

function option(value, text) {
  const opt = el("option", "", text);
  opt.value = value;
  return opt;
}

/** The setup wizard is open: nothing is connected yet because Notifications comes next. */
function inWizard() {
  const view = document.getElementById("setup-view");
  return Boolean(view && view.firstChild && !view.hidden && !view.classList.contains("hidden"));
}

/** Decide what the box and the line say from the connected channels (null: unknown). */
export function applyChannels(field, connected) {
  field.connected = connected;
  const native = window.__findplus_native === true;
  const ids = connected ? [...connected] : [];
  field.pick.hidden = ids.length < 2;
  field.select.replaceChildren();
  field.box.disabled = false;
  const labels = channelLabels(connected);
  if (connected === null) field.line.textContent = t("places.notify.unknown");
  else if (!ids.length && native) field.line.textContent = t("places.notify.native");
  else if (!ids.length) {
    field.box.checked = false;
    field.box.disabled = true;
    field.line.textContent = t(inWizard() ? "places.notify.noneWizard" : "places.notify.none");
  } else if (ids.length === 1) field.line.textContent = t("places.notify.sentTo", { channel: t(`alerts.channels.${ids[0]}`) });
  else {
    field.line.textContent = "";
    ids.forEach((id) => field.select.appendChild(option(id, labels[id] || t(`alerts.channels.${id}`))));
    field.select.appendChild(option(ALL, t("places.notify.all")));
    field.select.value = ids.includes("telegram") ? "telegram" : ids[0];
  }
}

/** Open the field for a new place: ticked again, channels looked up. */
export async function fillNotify(field) {
  field.box.checked = true;
  applyChannels(field, await connectedChannels());
}

/** `{notify, notify_channels?}` for POST /api/places. */
export function readNotify(field) {
  if (!field.box.checked || field.box.disabled) return { notify: false };
  if (field.pick.hidden || !field.connected) return { notify: true };
  const wanted = field.select.value === ALL ? [...field.connected] : [field.select.value];
  return { notify: true, notify_channels: wanted };
}
