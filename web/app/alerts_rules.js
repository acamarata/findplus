/*
 * Alerts tab: the rule cards. Split out of alerts.js at the PRI rule-7
 * 300-line file cap; the add/edit-rule dialog itself lives in
 * alerts_rule_dialog.js.
 *
 * Purpose    : List the alert rules, one compact card each: the rule's name, the
 *              rule in one plain sentence, an on/off switch, Edit and Delete.
 *              (The old nine-row table said the same thing nine times.)
 * Inputs     : GET/PUT/DELETE under /api/alerts/rules.
 * Outputs    : `li.fp-rule-card` rows inside #fp-rules-list.
 * Constraints: textContent only, never raw markup. alerts.js owns wiring the
 *              static buttons/dialog controls to these functions and re-exports
 *              `purge()`/`refreshAll()` for lock.js; this module has no top-level
 *              side effects of its own.
 */
"use strict";
import { markForLinks } from "./person_links.js";
import { $, showAlert } from "./state.js";
import { api } from "./api.js";
import { t, plural } from "./i18n.js";
import { openRuleDialog } from "./alerts_rule_dialog.js";
import { ruleSentence } from "./alerts_rule_sentence.js";
import { button } from "./components/button.js";
import { confirmDialog } from "./components/confirm-dialog.js";

export {
  fillOptions,
  openAddRuleDialog,
  saveRule,
  updateRuleTargetVisibility,
  updateTelegramTargetsVisibility,
} from "./alerts_rule_dialog.js";

export async function loadRules() {
  renderRulesList(await api("/api/alerts/rules"));
}
function ruleTargetLabel(rule) {
  if (rule.all_people) return t("alerts.everyone");
  if (rule.group_id) return rule.group_name || t("alerts.groupFallback", { id: rule.group_id });
  return rule.device_name || rule.device_id || t("common.emptyValue");
}
/** WP10 (gap-audit P13): the sentence names the Telegram subset, not just the
 *  bare channel -- null (every saved target) reads as plain "Telegram"; a list
 *  says how many chats, or that none are picked (dispatch.py skips Telegram
 *  for that rule). */
function channelDisplayLabel(rule, channelId) {
  const base = t("alerts.channels." + channelId);
  if (channelId !== "telegram" || rule.telegram_targets == null) return base;
  const count = rule.telegram_targets.length;
  return count === 0
    ? t("alerts.telegramNoChatsSelected", { channel: base })
    : plural("alerts.telegramTargetsCount", count, { channel: base, count });
}
/** The rule in plain words ("Tell me on Telegram when Sam Bag leaves School."). */
function sentenceFor(rule) {
  return ruleSentence({
    channels: rule.channels.map((c) => channelDisplayLabel(rule, c)),
    who: rule.all_people ? t("alerts.anyone") : ruleTargetLabel(rule),
    isGroup: rule.group_id != null,
    enter: rule.on_enter,
    exit: !!rule.on_exit,
    place: rule.place_name || "",
  });
}
function textBlock(rule) {
  const box = document.createElement("div");
  box.className = "fp-rule-card-text";
  const name = document.createElement("strong");
  name.className = "fp-rule-card-title";
  name.textContent = rule.name;
  const sentence = document.createElement("span");
  sentence.className = "fp-rule-row-sentence";
  sentence.textContent = sentenceFor(rule);
  box.append(name, markForLinks(sentence));
  return box;
}

/** UAT U13: the on/off switch, PUT-ing the single field. Dispatch already
 *  filters on `enabled` server-side (dispatch.py). A real checkbox drawn as a
 *  switch (alerts.css), so keyboard and screen readers get it for free. */
function enabledSwitch(rule, card) {
  const label = document.createElement("label");
  label.className = "fp-switch";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.setAttribute("role", "switch");
  input.checked = rule.enabled;
  input.setAttribute("aria-label", t("alerts.ruleEnabledLabel", { name: rule.name }));
  const text = document.createElement("span");
  text.className = "fp-switch-text";
  const paint = () => {
    text.textContent = t(input.checked ? "alerts.cards.on" : "alerts.cards.off");
    card.dataset.enabled = String(input.checked);
  };
  paint();
  input.addEventListener("change", async () => {
    const next = input.checked;
    paint();
    try {
      await api(`/api/alerts/rules/${rule.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next }),
      });
    } catch (err) {
      input.checked = !next;
      paint();
      if (err.message !== "Locked") {
        showAlert(t("alerts.ruleUpdateFailed", { name: rule.name, status: err.message }), "err");
      }
    }
  });
  label.append(input, text);
  return label;
}

function actionButton(label, ariaKey, rule, danger, onClick) {
  return button({
    label, size: "sm", variant: danger ? "danger" : "secondary",
    icon: danger ? undefined : "pencil", onClick,
    attrs: { "aria-label": t(ariaKey, { name: rule.name }) },
  });
}

function buildRuleCard(rule) {
  const card = document.createElement("li");
  card.className = "fp-rule-card";
  card.dataset.ruleId = String(rule.id);
  const controls = document.createElement("div");
  controls.className = "fp-rule-card-controls";
  controls.append(
    enabledSwitch(rule, card),
    actionButton(t("common.edit"), "alerts.cards.editAria", rule, false, () => openRuleDialog(rule)),
    actionButton(t("common.delete"), "alerts.cards.deleteAria", rule, true, () => deleteRule(rule.id, rule.name)),
  );
  card.append(textBlock(rule), controls);
  return card;
}

export function renderRulesList(rules) {
  const list = $("fp-rules-list");
  if (!list) return;
  list.replaceChildren(...rules.map(buildRuleCard));
  const empty = $("fp-rules-empty");
  if (empty) empty.hidden = rules.length > 0;
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
