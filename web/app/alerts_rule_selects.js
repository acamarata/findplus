/*
 * Alerts tab: the add/edit-rule dialog's Place/Device/Group selects. Split
 * out of alerts_rule_dialog.js at the PRI rule-7 300-line file cap (UAT6
 * N05's tracked-first/"Choose a device" fix pushed it past the limit).
 *
 * Purpose    : Populate the three plain <select> elements the rule dialog
 *              shows (Place, Device, Group) from the API. Device/Group lead
 *              with a "Choose…" placeholder so opening the dialog never
 *              silently defaults to whichever row happens to sort first
 *              (UAT6 N05: Save with nothing filled in used to target the
 *              first device in the list -- the untracked AirTag in this
 *              suite's seed data). Place is left as it was: a rule with no
 *              place filter is a normal, common choice, not a mistake to
 *              guard against.
 * Inputs     : GET /api/places, state.devices, GET /api/groups.
 * Outputs    : fillOptions()/fillLoading() (generic, reused by
 *              alerts_rules.js's own rows and alerts_rule_dialog.js),
 *              populateRuleSelects().
 * Constraints: textContent only, via DOM option nodes -- never raw markup.
 */
"use strict";
import { $, state, displayName } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";

export function fillOptions(select, items, mapFn) {
  while (select.firstChild) select.removeChild(select.firstChild);
  items.forEach((item) => {
    const [value, label] = mapFn(item);
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    select.appendChild(opt);
  });
}
/** One disabled placeholder, so an unfilled select never looks like "none exist". */
export function fillLoading(select) {
  fillOptions(select, [null], () => ["", t("common.loading")]);
}

/**
 * `state.devices`, loading it first when the boot has not filled it yet.
 *
 * The dialog used to read the module cache with nothing awaiting it, so
 * opening Add rule before the boot's device load landed produced an empty
 * device select and a rule that could not name a tracker (CF-P2-18). This is
 * the same `loadDevices()` the boot calls, imported dynamically to keep
 * devices.js off alerts.js's own import graph — never a second fetch path.
 */
async function ensureDevices() {
  if (state.devices && state.devices.length) return state.devices;
  try {
    const devices = await import("./devices.js");
    await devices.loadDevices();
  } catch (_) { /* locked or unreachable; an empty select is the honest result */ }
  return state.devices || [];
}

/**
 * The device select, tracked devices first: an alert on an untracked device
 * never fires (the poller never fetches its location), so a name sorted to
 * the top of a plain alphabetic list -- the untracked AirTag, in UAT6 N05's
 * seed data -- was one accidental click away from becoming a rule's target.
 * Untracked devices stay in the list (a device tracked later should not need
 * its rules rebuilt) but carry the same "(not polled)" suffix devices.js's
 * own filter already uses, and a blank "Choose a device" option leads every
 * render so opening the dialog never silently defaults to whichever device
 * happens to sort first (UAT6 N05).
 */
function fillDeviceSelect(devices) {
  const tracked = devices.filter((d) => d.is_tracked);
  const untracked = devices.filter((d) => !d.is_tracked);
  fillOptions($("fp-rule-device"), [null, ...tracked, ...untracked], (d) =>
    d === null
      ? ["", t("alerts.chooseDevice")]
      : [d.device_id, displayName(d) + (d.is_tracked ? "" : t("devices.notPolledSuffix"))],
  );
}

/** Same "nothing chosen by default" fix as fillDeviceSelect(), for the group target. */
function fillGroupSelect(groups) {
  fillOptions($("fp-rule-group"), [null, ...groups], (g) =>
    g === null ? ["", t("alerts.chooseGroup")] : [String(g.id), g.name],
  );
}

export async function populateRuleSelects() {
  const [places, devices] = await Promise.all([
    api("/api/places").catch(() => []),
    ensureDevices(),
  ]);
  fillOptions($("fp-rule-place"), places, (p) => [String(p.id), p.name]);
  // UAT U6: the rule form's own Device select shows the label too.
  fillDeviceSelect(devices);
  let groups = [];
  try {
    groups = await api("/api/groups");
  } catch (_) { /* unreachable too; an empty group select is harmless */ }
  fillGroupSelect(groups);
}
