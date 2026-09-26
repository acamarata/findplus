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
import { t, plural } from "./i18n.js";
import { openRuleDialog } from "./alerts_rule_dialog.js";
import { confirmDialog } from "./components/confirm-dialog.js";

export {
  fillOptions,
  openAddRuleDialog,
  saveRule,
  updateRuleTargetVisibility,
  updateTelegramTargetsVisibility,
} from "./alerts_rule_dialog.js";

export async function loadRules() {
  renderRulesTable(await api("/api/alerts/rules"));
}
function ruleTargetLabel(rule) {
  if (rule.group_id) return rule.group_name || t("alerts.groupFallback", { id: rule.group_id });
  return rule.device_name || rule.device_id || t("common.emptyValue");
}
/** WP10 (gap-audit P13): the Channels cell shows the Telegram subset, not
 *  just the bare channel name -- null (every saved target) reads exactly
 *  like before this feature existed; a non-null list says how many chats,
 *  or that none are picked (dispatch.py skips Telegram for that rule). */
function channelDisplayLabel(rule, channelId) {
  const base = t("alerts.channels." + channelId);
  if (channelId !== "telegram" || rule.telegram_targets == null) return base;
  const count = rule.telegram_targets.length;
  return count === 0
    ? t("alerts.telegramNoChatsSelected", { channel: base })
    : plural("alerts.telegramTargetsCount", count, { channel: base, count });
}
/** A labelled `<td>` for the phone-tier/narrow-pane card layout (components.css
 *  turns data-label into the row's own heading below a 500px container,
 *  UAT3 N16 -- the same convention alerts_deliveries.js's cell() uses). */
function cell(text, label) {
  const td = document.createElement("td");
  td.textContent = text;
  td.dataset.label = label;
  return td;
}
/** UAT U13: enabled/disabled toggle, PUT-ing the single field. Dispatch
 *  already filters on `enabled` server-side (dispatch.py); this is the only
 *  piece that was missing. */
function enabledToggleCell(rule) {
  const td = document.createElement("td");
  td.dataset.label = t("alerts.colEnabled");
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
/** UAT3 N16: at 1280 the table renders inside the ~348px side pane, and at
 *  375 the phone-tier pane is ~307px -- both already under the 500px
 *  `@container` gate components.css keys the delivery-log's card layout off
 *  (#tab-alerts sets container-type: inline-size), so the same data-label
 *  convention turns each row into a card there instead of an 8-column table
 *  wider than either box. Edit/Delete get their own labelled cell like every
 *  other column, rather than sitting unlabelled at the end of the card. */
function buildRuleRow(rule) {
  const tr = document.createElement("tr");
  tr.append(
    cell(rule.name, t("alerts.colName")),
    cell(rule.place_name || t("common.emptyValue"), t("alerts.colPlace")),
    cell(ruleTargetLabel(rule), t("alerts.colTarget")),
    cell(rule.on_enter ? t("common.yes") : t("common.no"), t("alerts.colOnEnter")),
    cell(rule.on_exit ? t("common.yes") : t("common.no"), t("alerts.colOnExit")),
    cell(
      rule.channels.map((c) => channelDisplayLabel(rule, c)).join(", "),
      t("alerts.rules.channelsHeader"),
    ),
    enabledToggleCell(rule),
  );
  const actions = document.createElement("td");
  actions.dataset.label = t("alerts.colActions");
  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "btn btn-tiny";
  editBtn.textContent = t("common.edit");
  editBtn.addEventListener("click", () => openRuleDialog(rule));
  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.className = "btn btn-tiny";
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
  const confirmed = await confirmDialog({
    title: t("common.delete"),
    body: t("alerts.confirmDeleteRule", { name }),
    confirmLabel: t("common.delete"),
    danger: true,
  });
  if (!confirmed) return;
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
