/*
 * Alerts tab: rules table + the add-rule dialog. Split out of alerts.js at
 * the PRI rule-7 300-line file cap.
 *
 * Purpose    : List, add and delete alert rules; populate the add-rule
 *              dialog's place/device/group selects.
 * Inputs     : GET/POST/DELETE under /api/alerts/rules; GET /api/places,
 *              state.devices, GET /api/groups.
 * Outputs    : The rules table and add-rule dialog inside #tab-alerts.
 * Constraints: textContent only, never raw markup. alerts.js owns wiring
 *              the static buttons/dialog controls to these functions and
 *              re-exports `purge()`/`refreshAll()` for lock.js — this
 *              module has no top-level side effects of its own.
 */
"use strict";
import { $, state, displayName, showAlert } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";
import { renderChannelPicker, readChannelPicker } from "./components/channel-picker.js";
import { BASE_CHANNELS, availableChannels, connectedChannels, channelLabels } from "./alerts_rule_channels.js";

export async function loadRules() {
  renderRulesTable(await api("/api/alerts/rules"));
}
function ruleTargetLabel(rule) {
  if (rule.group_id) return rule.group_name || t("alerts.groupFallback", { id: rule.group_id });
  return rule.device_name || rule.device_id || t("common.emptyValue");
}
function cell(text) {
  const td = document.createElement("td");
  td.textContent = text;
  return td;
}
/** UAT U13: enabled/disabled toggle, PUT-ing the single field. Dispatch
 *  already filters on `enabled` server-side (dispatch.py); this is the only
 *  piece that was missing. */
function enabledToggleCell(rule) {
  const td = document.createElement("td");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = rule.enabled;
  input.setAttribute("aria-label", t("alerts.ruleEnabledLabel", { name: rule.name }));
  input.addEventListener("change", async () => {
    const next = input.checked;
    try {
      await api(`/api/alerts/rules/${rule.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next }),
      });
    } catch (err) {
      input.checked = !next;
      if (err.message !== "Locked") {
        showAlert(t("alerts.ruleUpdateFailed", { name: rule.name, status: err.message }), "err");
      }
    }
  });
  td.appendChild(input);
  return td;
}
function buildRuleRow(rule) {
  const tr = document.createElement("tr");
  tr.append(
    cell(rule.name), cell(rule.place_name || t("common.emptyValue")), cell(ruleTargetLabel(rule)),
    cell(rule.on_enter ? t("common.yes") : t("common.no")),
    cell(rule.on_exit ? t("common.yes") : t("common.no")),
    cell(rule.channels.join(", ")),
    enabledToggleCell(rule),
  );
  const actions = document.createElement("td");
  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.textContent = t("common.edit");
  editBtn.addEventListener("click", () => openRuleDialog(rule));
  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.textContent = t("common.delete");
  delBtn.addEventListener("click", () => deleteRule(rule.id, rule.name));
  actions.append(editBtn, delBtn);
  tr.appendChild(actions);
  return tr;
}
export function renderRulesTable(rules) {
  const tbody = $("fp-rules-tbody");
  if (!tbody) return;
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
  rules.forEach((rule) => tbody.appendChild(buildRuleRow(rule)));
}
async function deleteRule(id, name) {
  if (!window.confirm(t("alerts.confirmDeleteRule", { name }))) return;
  // A refused delete used to leave the row on screen with no message, which is
  // indistinguishable from a no-op (E1 honesty round 3 F10). Through api(),
  // not a raw fetch(), so a 401 shows the lock screen instead of reading as a
  // failed delete, and the route's 204 is handled (CF-P2-E5-1).
  try {
    await api(`/api/alerts/rules/${id}`, { method: "DELETE" });
  } catch (err) {
    if (err.message !== "Locked") {
      showAlert(t("alerts.deleteRuleFailed", { name, status: err.message }), "err");
    }
    return;
  }
  await loadRules();
}
/* add-rule dialog */
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
  $("fp-add-rule-dialog").setAttribute("aria-label", t(rule ? "alerts.editRule" : "alerts.addRule"));
  // Everything the dialog shows without a round trip is set first and the
  // dialog opens at once; the three selects carry a "Loading…" placeholder
  // until their data lands, rather than the dialog hanging shut on a fetch.
  ["fp-rule-place", "fp-rule-device", "fp-rule-group"].forEach((id) => fillLoading($(id)));
  $("fp-rule-name").value = rule ? rule.name : "";
  $("fp-rule-on-enter").checked = rule ? rule.on_enter : true;
  $("fp-rule-on-exit").checked = rule ? !!rule.on_exit : false;
  // The API default (routes_alerts_rules.py:33) and the CLI's, so a rule
  // created here does not suppress for twice as long as one created
  // with `findplus alerts add` (E1 honesty round 3 F9).
  $("fp-rule-cooldown").value = String(rule ? rule.cooldown_minutes : 30);
  const isGroup = !!(rule && rule.group_id != null);
  $("fp-rule-target-device").checked = !isGroup;
  $("fp-rule-target-group").checked = isGroup;
  $("fp-rule-target-device").disabled = $("fp-rule-target-group").disabled = !!rule;
  updateRuleTargetVisibility();
  $("fp-rule-error").textContent = "";

  const initialChannels = rule ? rule.channels : ["telegram"];
  renderChannelPicker($("fp-rule-channels"), {
    selected: initialChannels,
    available: BASE_CHANNELS,
    labels: channelLabels(null),
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
  // `initialChannels`, never readChannelPicker() off the current DOM (UAT
  // U12): a fresh open's selection always traces back to `rule`/the default.
  renderChannelPicker($("fp-rule-channels"), {
    selected: initialChannels,
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

export async function saveRule() {
  const dlg = $("fp-add-rule-dialog");
  const isDevice = $("fp-rule-target-device").checked;
  const body = {
    name: $("fp-rule-name").value,
    // An empty <select> gives "", and Number("") is 0 — a place_id no row has,
    // so PRAGMA foreign_keys=ON turned the save into a raw 500 in the dialog
    // (E1 honesty round 3 F8). null is what "nothing chosen" means.
    place_id: numberOrNull($("fp-rule-place").value),
    on_enter: $("fp-rule-on-enter").checked,
    on_exit: $("fp-rule-on-exit").checked,
    // No client-side guard on an empty set: the server's 422 is the one
    // rule, and saveRule already routes an api() rejection to the dialog.
    channels: readChannelPicker($("fp-rule-channels")),
    cooldown_minutes: Number($("fp-rule-cooldown").value),
  };
  if (!editingRuleId) {
    // RuleUpdate has no device_id/group_id field, and the dialog disables
    // both target inputs while editing to match (UAT U13).
    body.device_id = (isDevice ? $("fp-rule-device").value : "") || null;
    body.group_id = isDevice ? null : numberOrNull($("fp-rule-group").value);
  }
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
    await loadRules();
  } catch (err) {
    // api() shows the lock screen for a 401; anything else is shown here.
    if (err.message !== "Locked") $("fp-rule-error").textContent = err.message;
  }
}
