/*
 * The group member checklist, shared by the Groups tab dialog and the wizard.
 *
 * Purpose    : Draw every known device as a checkbox row, and say plainly why
 *              a row cannot be ticked or why there is nothing to tick. Right
 *              after a first sign-in nothing is tracked yet and no device has
 *              a location; the old list showed an empty box, and Save then
 *              answered "Select at least one member." with no way to see why.
 * Inputs     : The container (a fieldset or div that may hold a <legend>) and
 *              the GET /api/devices rows. `wizard: true` words the "track
 *              some first" hint for the setup step instead of the dashboard.
 * Outputs    : Hint paragraphs, a "Select all" toggle and `.fp-member-row`
 *              labels with `input[data-device-id]`. Untracked devices are
 *              listed disabled: Find+ only polls tracked devices, so a group
 *              made of them could never produce a location or an alert.
 * Constraints: Built with createElement/textContent only. Devices that share
 *              a display name get the last four characters of their id so two
 *              "Ali Pixel 8a" rows are never identical.
 */
"use strict";

import { t, plural } from "./i18n.js";
import { displayName } from "./state.js";
import { memberRow } from "./groups_dialog_dom.js";

function hint(text) {
  const p = document.createElement("p");
  p.className = "fp-field-hint fp-members-hint";
  p.textContent = text;
  return p;
}

/** Display names that more than one device carries. */
function repeatedNames(devices) {
  const seen = new Map();
  devices.forEach((d) => {
    const key = displayName(d);
    seen.set(key, (seen.get(key) || 0) + 1);
  });
  return new Set([...seen].filter(([, n]) => n > 1).map(([name]) => name));
}

function selectAllButton(box) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn-tiny btn-secondary fp-members-all";
  const boxes = () => [...box.querySelectorAll("input[data-device-id]:not([disabled])")];
  const sync = () => {
    const all = boxes().length > 0 && boxes().every((b) => b.checked);
    btn.textContent = all ? t("groups.members.clear") : t("groups.members.select_all");
  };
  btn.addEventListener("click", () => {
    const all = boxes().every((b) => b.checked);
    boxes().forEach((b) => { b.checked = !all; });
    sync();
  });
  // One live listener per box: a re-render replaces the button, not the box.
  if (box._fpMembersSync) box.removeEventListener("change", box._fpMembersSync);
  box._fpMembersSync = sync;
  box.addEventListener("change", sync);
  sync();
  return btn;
}

function deviceRow(device, repeated, tracked) {
  const suffix = repeated.has(displayName(device)) ? ` (${String(device.device_id).slice(-4)})` : "";
  const row = memberRow(device, { disabled: !tracked, suffix });
  if (!tracked) row.title = t("groups.members.untracked_row");
  return row;
}

/** Replace everything in `box` except its legend with the current checklist. */
export function renderMemberList(box, devices, { wizard = false } = {}) {
  [...box.children].forEach((child) => { if (child.tagName !== "LEGEND") child.remove(); });
  if (!devices.length) {
    box.append(hint(t("groups.members.none_found")));
    return;
  }
  const tracked = devices.filter((d) => d.is_tracked);
  const untracked = devices.filter((d) => !d.is_tracked);
  const repeated = repeatedNames(devices);
  if (!tracked.length) {
    const key = wizard ? "groups.members.none_tracked_setup" : "groups.members.none_tracked";
    box.append(hint(t(key, { count: devices.length })));
  } else {
    box.append(selectAllButton(box));
    tracked.forEach((d) => box.append(deviceRow(d, repeated, true)));
  }
  if (untracked.length) {
    const key = wizard ? "groups.members.untracked_note_setup" : "groups.members.untracked_note";
    box.append(hint(plural("groups.members.untracked_count", untracked.length, { count: untracked.length })
      + " " + t(key)));
    untracked.forEach((d) => box.append(deviceRow(d, repeated, false)));
  }
}
