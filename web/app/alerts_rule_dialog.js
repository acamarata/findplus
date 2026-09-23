/*
 * Alerts tab: the add/edit-rule dialog. Split out of alerts_rules.js at the
 * PRI rule-7 300-line file cap (UAT2 U11/U32/N7 pushed the combined file
 * over it).
 *
 * Purpose    : Populate and drive the shared add/edit-rule <dialog> -- its
 *              place/device/group/channel selections and the save round
 *              trip. alerts_rules.js's buildRuleRow() imports
 *              openRuleDialog() from here for its Edit button; this module
 *              dynamic-imports alerts_rules.js back for loadRules() after a
 *              save, the same way ensureDevices() below keeps devices.js off
 *              this file's static import graph -- never a circular one.
 * Inputs     : GET /api/places, state.devices, GET /api/groups,
 *              availableChannels()/connectedChannels() (alerts_rule_
 *              channels.js). POST/PUT under /api/alerts/rules on save.
 * Outputs    : The dialog's own fields, plus a saved rule POST/PUT.
 * Constraints: textContent only, never raw markup. alerts.js owns wiring
 *              the static Save/Cancel/target-radio controls to these
 *              functions -- this module has no top-level side effects.
 */
"use strict";
import { $, state, displayName } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";
import { renderChannelPicker, readChannelPicker } from "./components/channel-picker.js";
import { BASE_CHANNELS, availableChannels, connectedChannels, channelLabels } from "./alerts_rule_channels.js";

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
function fillLoading(select) {
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

async function populateRuleSelects() {
  const [places, devices] = await Promise.all([
    api("/api/places").catch(() => []),
    ensureDevices(),
  ]);
  fillOptions($("fp-rule-place"), places, (p) => [String(p.id), p.name]);
  // UAT U6: the rule form's own Device select shows the label too.
  fillOptions($("fp-rule-device"), devices, (d) => [d.device_id, displayName(d)]);
  let groups = [];
  try {
    groups = await api("/api/groups");
  } catch (_) { /* unreachable too; an empty group select is harmless */ }
  fillOptions($("fp-rule-group"), groups, (g) => [String(g.id), g.name]);
}
export function updateRuleTargetVisibility() {
  const isDevice = $("fp-rule-target-device").checked;
  $("fp-rule-device").classList.toggle("hidden", !isDevice);
  $("fp-rule-group").classList.toggle("hidden", isDevice);
}

/** null for "Add rule"; the rule row being edited otherwise (UAT U13). */
let editingRuleId = null;

/** The `connected` Set the dialog's last open resolved (or null, "unknown"
 *  -- the channels fetch failed). saveRule()'s own U11 guard reads this;
 *  it is not local to openRuleDialog() because saveRule() runs later, off
 *  the Save click, not off the same call stack. */
let lastConnectedChannels = null;

/** UAT2 U11: a new rule's real default -- every channel that can actually
 *  deliver right now. native always can (no credential concept);
 *  telegram/webhook/whatsapp only once `connected` says so. `connected ===
 *  null` (the channels fetch failed) means nothing pre-ticked rather than a
 *  guess. Editing keeps the rule's own saved channels untouched. */
function defaultSelectedChannels(rule, initialChannels, available, connected) {
  if (rule) return initialChannels;
  return available.filter((id) => id === "native" || (connected && connected.has(id)));
}

/** The name/on-enter/on-exit/cooldown/target-radio fields openRuleDialog()
 *  resets on every open -- pulled out to keep that function under the PRI
 *  rule-7 50-line cap. The API default cooldown (routes_alerts_rules.py:33)
 *  matches the CLI's, so a rule created here does not suppress for twice as
 *  long as one created with `findplus alerts add` (E1 honesty round 3 F9). */
function seedRuleFields(rule) {
  $("fp-rule-name").value = rule ? rule.name : "";
  $("fp-rule-on-enter").checked = rule ? rule.on_enter : true;
  $("fp-rule-on-exit").checked = rule ? !!rule.on_exit : false;
  $("fp-rule-cooldown").value = String(rule ? rule.cooldown_minutes : 30);
  const isGroup = !!(rule && rule.group_id != null);
  $("fp-rule-target-device").checked = !isGroup;
  $("fp-rule-target-group").checked = isGroup;
  $("fp-rule-target-device").disabled = $("fp-rule-target-group").disabled = !!rule;
  updateRuleTargetVisibility();
}

/**
 * Open the add/edit-rule dialog, always reset to `rule`'s values (or blank
 * defaults for a new rule) -- never to whatever the dialog last held, so a
 * second "Add rule" can never inherit an earlier rule's ticks (UAT U12).
 *
 * RuleUpdate has no device_id/group_id field (the API never lets an edit
 * retarget a rule -- routes_alerts_rules.py's RuleUpdate), so both target
 * inputs are disabled while editing; saveRule() below matches by only
 * sending a target on create.
 */
export async function openRuleDialog(rule = null) {
  editingRuleId = rule ? rule.id : null;
  // UAT2 U32/N7: the dialog carries a real <h2> now (aria-labelledby points
  // at it, alerts.html) -- the title says which mode this is.
  $("fp-add-rule-dialog-title").textContent = t(rule ? "alerts.editRule" : "alerts.newRule");
  // Everything the dialog shows without a round trip is set first and the
  // dialog opens at once; the three selects carry a "Loading…" placeholder
  // until their data lands, rather than the dialog hanging shut on a fetch.
  ["fp-rule-place", "fp-rule-device", "fp-rule-group"].forEach((id) => fillLoading($(id)));
  seedRuleFields(rule);
  $("fp-rule-error").textContent = "";

  // UAT2 U11: nothing pre-ticked yet -- the real default needs `connected`,
  // resolved below. Editing starts from the rule's own saved channels.
  const initialChannels = rule ? rule.channels : [];
  renderChannelPicker($("fp-rule-channels"), {
    selected: initialChannels, available: BASE_CHANNELS, labels: channelLabels(null),
  });

  $("fp-add-rule-dialog").showModal();

  // In parallel, not in series: the channel list is usually already resolved,
  // and it must never add a round-trip to the time the dialog takes to open.
  const [, available, connected] = await Promise.all([
    populateRuleSelects(), availableChannels(), connectedChannels(),
  ]);
  if (rule) {
    $("fp-rule-place").value = rule.place_id != null ? String(rule.place_id) : "";
    $("fp-rule-device").value = rule.device_id || "";
    $("fp-rule-group").value = rule.group_id != null ? String(rule.group_id) : "";
  }
  lastConnectedChannels = connected;
  // defaultSelectedChannels()/`initialChannels`, never readChannelPicker()
  // off the current DOM (UAT U12): a fresh open always retraces `rule`/the
  // default, never whatever the dialog last held. Every box stays tickable
  // either way (U11's own component test) -- saveRule() below is what
  // catches an all-unconnected save, instead of disabling every checkbox.
  renderChannelPicker($("fp-rule-channels"), {
    selected: defaultSelectedChannels(rule, initialChannels, available, connected),
    available,
    labels: channelLabels(connected),
    connected,
  });
}
export const openAddRuleDialog = () => openRuleDialog(null);
/** "" -> null, so an unchosen select is not silently id 0. */
function numberOrNull(value) {
  const n = Number(value);
  return value === "" || Number.isNaN(n) || n === 0 ? null : n;
}

function buildRulePayload(channels) {
  const isDevice = $("fp-rule-target-device").checked;
  const body = {
    name: $("fp-rule-name").value,
    // An empty <select> gives "", and Number("") is 0 — a place_id no row has,
    // so PRAGMA foreign_keys=ON turned the save into a raw 500 in the dialog
    // (E1 honesty round 3 F8). null is what "nothing chosen" means.
    place_id: numberOrNull($("fp-rule-place").value),
    on_enter: $("fp-rule-on-enter").checked,
    on_exit: $("fp-rule-on-exit").checked,
    channels,
    cooldown_minutes: Number($("fp-rule-cooldown").value),
  };
  if (!editingRuleId) {
    // RuleUpdate has no device_id/group_id field, and the dialog disables
    // both target inputs while editing to match (UAT U13).
    body.device_id = (isDevice ? $("fp-rule-device").value : "") || null;
    body.group_id = isDevice ? null : numberOrNull($("fp-rule-group").value);
  }
  return body;
}

export async function saveRule() {
  const dlg = $("fp-add-rule-dialog");
  const channels = readChannelPicker($("fp-rule-channels"));
  // UAT2 U11: the picker still lets an unconnected channel be ticked (a
  // fresh install with nothing connected yet must be able to create its
  // first rule), so a selection that is entirely unconnected channels can
  // still reach here -- refuse it before the round trip, with the same
  // reason the server itself now enforces (routes_alerts_rules.py). Skipped
  // when nothing is ticked at all (the server's own "channels required" 422
  // already covers that, unrelated to connection status) or when `connected`
  // is unknown (the fetch failed): the server is the only side that still
  // knows then.
  if (
    channels.length > 0 &&
    lastConnectedChannels &&
    !channels.some((id) => id === "native" || lastConnectedChannels.has(id))
  ) {
    $("fp-rule-error").textContent = t("alerts.noConnectedChannel");
    return;
  }
  const body = buildRulePayload(channels);
  const [path, method] = editingRuleId
    ? [`/api/alerts/rules/${editingRuleId}`, "PUT"]
    : ["/api/alerts/rules", "POST"];
  try {
    await api(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    dlg.close();
    const { loadRules } = await import("./alerts_rules.js");
    await loadRules();
  } catch (err) {
    // api() shows the lock screen for a 401; anything else is shown here.
    if (err.message !== "Locked") $("fp-rule-error").textContent = err.message;
  }
}
