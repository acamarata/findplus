/*
 * One device row of the wizard's Devices step.
 *
 * Purpose    : The tick box, badge, name, label field and Edit button that
 *              make up a row, kept out of devices.js so that file stays the
 *              step (render/onEnter/onNext) and nothing else.
 * Inputs     : ctx (api/showAlert), one device from GET /api/devices, the
 *              refresh callback to run after the edit dialog closes, and
 *              defaultChecked (UAT U15: devices.js's "nobody tracked yet"
 *              flag, so a fresh account starts every row ticked instead of
 *              every row silently unticked).
 * Outputs    : An Element; PATCH /api/devices/{id} on a debounced label edit.
 * Constraints: createElement and textContent only — a tracker's name comes
 *              from the provider account, so it is never written as markup.
 */
"use strict";

import { t } from "../i18n.js";
import { renderBadge } from "../components/badge.js";
import { openEditDialog } from "../devices_dialog.js";

const PATCH_DEBOUNCE_MS = 500;

/** Collapse a burst of keystrokes into one request. */
export function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function patchDevice(ctx, id, changes) {
  return ctx
    .api(`/api/devices/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    })
    .catch((err) => ctx.showAlert(err.message, "err"));
}

/**
 * Open the Devices dialog's own editor for the icon and colour pickers.
 *
 * The same entry point devices.js uses, rather than a second inline copy of
 * both pickers per row: 48 icon buttons times every discovered tracker is not
 * a list anyone can read, and that dialog already owns the PATCH.
 */
function editButton(ctx, device, onClosed) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-tiny";
  btn.textContent = t("setup.devices.edit");
  btn.addEventListener("click", () => {
    openEditDialog(device.device_id, device);
    const dlg = document.getElementById("fp-device-dialog");
    if (dlg) dlg.addEventListener("close", onClosed, { once: true });
  });
  return btn;
}

function trackBox(device, defaultChecked) {
  const track = document.createElement("input");
  track.type = "checkbox";
  // UAT U15: a device already tracked (e.g. re-entering this step) keeps its
  // own state; on a fresh account where nothing is tracked yet, defaultChecked
  // (every row gets the same value: "no one is tracked yet") ticks every row
  // instead of leaving all of them silently unticked.
  track.checked = device.is_tracked || defaultChecked;
  track.dataset.track = "";
  track.dataset.deviceId = device.device_id;
  track.setAttribute("aria-label", t("setup.devices.trackFor", { name: device.name || device.device_id }));
  return track;
}

function labelInput(ctx, device) {
  const label = document.createElement("input");
  label.type = "text";
  label.value = device.label || "";
  label.placeholder = t("setup.devices.label_placeholder");
  label.addEventListener(
    "input",
    debounce(
      () => patchDevice(ctx, device.device_id, { label: label.value.trim() }),
      PATCH_DEBOUNCE_MS
    )
  );
  return label;
}

export function deviceRow(ctx, device, onClosed, defaultChecked) {
  const row = document.createElement("div");
  // fp-setup-device-row: this row has five children (track, badge, name,
  // label input, edit button), not the simple label+control pair the
  // generic .fp-dialog-field mobile rule assumes; see responsive.css.
  row.className = "fp-dialog-field fp-setup-device-row";
  const badge = document.createElement("span");
  badge.className = "fp-device-badge";
  badge.append(
    renderBadge({
      icon: device.icon || "letter",
      color: device.color,
      label: device.label,
      name: device.name,
      size: 24,
    })
  );
  const name = document.createElement("span");
  name.textContent = device.name || device.device_id;
  row.append(
    trackBox(device, defaultChecked),
    badge,
    name,
    labelInput(ctx, device),
    editButton(ctx, device, onClosed)
  );
  return row;
}
