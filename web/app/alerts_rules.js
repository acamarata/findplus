/*
 * Alerts tab: the rules table. Split out of alerts.js at the PRI rule-7
 * 300-line file cap; the add/edit-rule dialog itself lives in
 * alerts_rule_dialog.js (split again at the same cap, UAT2 U11/U32/N7).
 *
 * Purpose    : List and delete alert rules; open the shared dialog for
 *              add/edit.
 * Inputs     : GET/DELETE under /api/alerts/rules.
 * Outputs    : The rules table inside #tab-alerts.
 * Constraints: textContent only, never raw markup. alerts.js owns wiring
 *              the static buttons/dialog controls to these functions and
 *              re-exports `purge()`/`refreshAll()` for lock.js — this
 *              module has no top-level side effects of its own.
 */
"use strict";
import { $, showAlert } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";
import { openRuleDialog } from "./alerts_rule_dialog.js";

export { fillOptions, openAddRuleDialog, saveRule, updateRuleTargetVisibility } from "./alerts_rule_dialog.js";

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
