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
import { $, state, showAlert } from "./state.js";
import { api } from "./api.js";

export async function loadRules() {
  renderRulesTable(await api("/api/alerts/rules"));
}
function ruleTargetLabel(rule) {
  if (rule.group_id) return rule.group_name || `group ${rule.group_id}`;
  return rule.device_name || rule.device_id || "—";
}
function cell(text) {
  const td = document.createElement("td");
  td.textContent = text;
  return td;
}
function buildRuleRow(rule) {
  const tr = document.createElement("tr");
  tr.append(
    cell(rule.name), cell(rule.place_name || "—"), cell(ruleTargetLabel(rule)),
    cell(rule.on_enter ? "yes" : "no"), cell(rule.on_exit ? "yes" : "no"), cell(rule.channel),
  );
  const actions = document.createElement("td");
  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.textContent = "Delete";
  delBtn.addEventListener("click", () => deleteRule(rule.id, rule.name));
  actions.appendChild(delBtn);
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
  if (!window.confirm(`Delete rule "${name}"?`)) return;
  // A refused delete used to leave the row on screen with no message, which is
  // indistinguishable from a no-op (E1 honesty round 3 F10).
  const res = await fetch(`/api/alerts/rules/${id}`, { method: "DELETE" });
  if (!res.ok) {
    showAlert(`Could not delete "${name}" (${res.status}).`, "err");
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
async function populateRuleSelects() {
  fillOptions($("fp-rule-place"), await api("/api/places"), (p) => [String(p.id), p.name]);
  fillOptions($("fp-rule-device"), state.devices, (d) => [d.device_id, d.name]);
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
export async function openAddRuleDialog() {
  await populateRuleSelects();
  $("fp-rule-name").value = "";
  $("fp-rule-on-enter").checked = true;
  $("fp-rule-on-exit").checked = false;
  // The API default (routes_alerts_rules.py:33) and the CLI's, so a rule
  // created here does not suppress for twice as long as one created
  // with `findplus alerts add` (E1 honesty round 3 F9).
  $("fp-rule-cooldown").value = "30";
  $("fp-rule-target-device").checked = true;
  updateRuleTargetVisibility();
  $("fp-rule-error").textContent = "";
  $("fp-add-rule-dialog").showModal();
}
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
    device_id: (isDevice ? $("fp-rule-device").value : "") || null,
    group_id: isDevice ? null : numberOrNull($("fp-rule-group").value),
    on_enter: $("fp-rule-on-enter").checked,
    on_exit: $("fp-rule-on-exit").checked,
    channel: $("fp-rule-channel").value,
    cooldown_minutes: Number($("fp-rule-cooldown").value),
  };
  try {
    await api("/api/alerts/rules", {
      method: "POST",
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
