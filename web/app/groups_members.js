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

import { api } from "./api.js";
import { state, displayName } from "./state.js";
import { t, plural } from "./i18n.js";
import { labelMap, tailOf } from "./device_label.js";
import { memberRow } from "./groups_dialog_dom.js";

function hint(text) {
  const p = document.createElement("p");
  p.className = "fp-field-hint fp-members-hint";
  p.textContent = text;
  return p;
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

function deviceRow(device, labels, tracked) {
  const suffix = tailOf(device, labels); // UAT #7: an id tail only on a name clash
  const row = memberRow(device, { disabled: !tracked, suffix });
  if (!tracked) row.title = t("groups.members.untracked_row");
  return row;
}

/** The poll interval in minutes, from the config the dashboard loaded, else the setting. */
function pollInterval() {
  const n = Number((state.config && state.config.poll_interval_minutes)
    || (state.settings && state.settings["poll.interval_minutes"]));
  return n > 0 ? n : null;
}

/** What tracking one more device costs, in words (or the generic sentence if unknown). */
function trackCost() {
  const interval = pollInterval();
  if (!interval) return t("groups.members.track_cost_unknown");
  const rate = Math.round((60 * 10) / interval) / 10;
  return t("groups.members.track_cost", { rate, interval });
}

/**
 * The one-click "Track this tracker" button beside an untracked device. It turns
 * tracking on for that device only (PATCH /api/devices/{id}), re-reads the list
 * and ticks the device, keeping every other tick. The cost sits in the note
 * above the rows (`describedBy`), so the person reads it before pressing.
 */
function trackButton(device, box, name, describedBy) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn-tiny btn-secondary fp-member-track";
  btn.textContent = t("groups.members.track_button");
  btn.setAttribute("aria-label", `${t("groups.members.track_button")}: ${name}`);
  btn.setAttribute("aria-describedby", describedBy);
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = t("groups.members.tracking");
    try {
      const ticked = new Set(
        [...box.querySelectorAll("input[data-device-id]:checked")].map((i) => i.dataset.deviceId)
      );
      await api(`/api/devices/${encodeURIComponent(device.device_id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tracked: true }),
      });
      const { devices } = await api("/api/devices");
      // Bring the filter, header and footer in line; a failure there is not this action's.
      import("./devices.js").then((m) => m.loadDevices()).catch(() => {});
      ticked.add(device.device_id);
      renderMemberList(box, devices);
      applyMemberSelection(box, ticked);
    } catch (err) {
      if (err.message === "Locked") return;
      btn.disabled = false;
      btn.textContent = t("groups.members.track_button");
      box.append(hint(t("groups.members.track_failed", { name, message: err.message })));
    }
  });
  return btn;
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
  const labels = labelMap(devices);
  if (!tracked.length) {
    const key = wizard ? "groups.members.none_tracked_setup" : "groups.members.none_tracked";
    box.append(hint(t(key, { count: devices.length })));
  } else {
    box.append(selectAllButton(box));
    tracked.forEach((d) => box.append(deviceRow(d, labels, true)));
  }
  if (untracked.length) {
    const key = wizard ? "groups.members.untracked_note_setup" : "groups.members.untracked_note_track";
    const note = hint(plural("groups.members.untracked_count", untracked.length, { count: untracked.length })
      + " " + t(key) + (wizard ? "" : " " + trackCost()));
    note.id = "fp-members-untracked-note";
    box.append(note);
    untracked.forEach((d) => {
      const row = deviceRow(d, labels, false);
      if (wizard) { box.append(row); return; }
      const line = document.createElement("div");
      line.className = "fp-member-line";
      line.append(row, trackButton(d, box, displayName(d) + tailOf(d, labels), note.id));
      box.append(line);
    });
  }
}

/**
 * Tick `ids` in a rendered checklist. A member that is ticked but no longer
 * tracked (it was untracked after the group was made) gets an enabled box and a
 * "not tracked" tag, so it can be unticked; a disabled box could never be.
 */
export function applyMemberSelection(box, ids) {
  box.querySelectorAll("input[data-device-id]").forEach((input) => {
    input.checked = ids.has(input.dataset.deviceId);
    if (!input.checked || !input.disabled) return;
    input.disabled = false;
    const row = input.closest(".fp-member-row");
    if (!row) return;
    row.classList.remove("fp-member-row--off");
    const tag = document.createElement("span");
    tag.className = "fp-field-hint fp-member-untracked";
    tag.textContent = t("groups.members.untracked_tag");
    row.append(tag);
  });
  // Programmatic ticks fire no change event; resync the Select all label.
  box.dispatchEvent(new Event("change"));
}
