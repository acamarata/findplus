/*
 * Alerts tab: the add/edit-rule dialog's per-rule Telegram target picker
 * (WP10, gap-audit P13). Split out of alerts_rule_dialog.js at the PRI
 * rule-7 300-line file cap, the same reason alerts_rule_selects.js was
 * split out of it earlier.
 *
 * Purpose    : Owner ask -- a rule may notify a group, a person, or a few
 *              people, not every saved Telegram chat. "All chats" (checked
 *              by default) means `telegram_targets: null` on save, matching
 *              every rule's pre-1.1.3 behaviour exactly when left alone;
 *              unticking it reveals a checkbox per saved chat (reusing
 *              components/channel-picker.js -- a chat id/label pair renders
 *              identically to a channel id/label pair, so this never needed
 *              its own picker widget) and reads back whatever subset is
 *              checked, possibly none.
 * Inputs     : The rule being edited (or null), and alerts_rule_channels.js's
 *              telegramTargets() ({ids, labels}).
 * Outputs    : seedTelegramTargetsFields() renders the field; readTelegram
 *              TargetsSelection() reads it for the save payload;
 *              updateTelegramTargetsVisibility() shows the whole field only
 *              while "telegram" is ticked in the main channel picker, and
 *              the per-chat list only while "All chats" is unticked --
 *              alerts.js wires both triggers to it once (static markup).
 * Constraints: textContent only (renderChannelPicker already guarantees
 *              this). No i18n import: labels come from the saved targets
 *              themselves, same as alerts_telegram_targets.js's chip row.
 */
"use strict";
import { $ } from "./state.js";
import { renderChannelPicker, readChannelPicker } from "./components/channel-picker.js";

/** Whether "telegram" is one of the currently ticked channels in the main
 *  channel picker -- the gate for showing this field at all. */
function telegramChannelIsTicked() {
  return !!$("fp-rule-channels").querySelector("input[data-channel=telegram]:checked");
}

/** Field hidden entirely unless telegram is ticked; the per-chat list hidden
 *  whenever "All chats" is ticked. Wired by alerts.js to both the channel
 *  picker's and the all-chats checkbox's `change` events, and called once
 *  more after seeding so a freshly opened dialog starts in the right state. */
export function updateTelegramTargetsVisibility() {
  const field = $("fp-rule-telegram-targets-field");
  if (!field) return;
  field.hidden = !telegramChannelIsTicked();
  // The "hidden" toggle lives on the wrapper, never on #fp-rule-telegram-
  // targets-list itself: that div's own "fp-channel-picker" class sets
  // `display: flex` at equal CSS specificity to (and loaded after) the
  // plain "hidden" utility class, which would otherwise silently outrank it.
  $("fp-rule-telegram-targets-list-wrap").classList.toggle(
    "hidden",
    $("fp-rule-telegram-all-chats").checked,
  );
}

/**
 * Render the field for `rule` (null for a new rule): "All chats" ticked and
 * the per-chat list empty/hidden when `rule.telegram_targets` is null (or
 * there is no rule yet); otherwise "All chats" unticked and the saved
 * subset (possibly empty) ticked in the list.
 */
export function seedTelegramTargetsFields(rule, { ids, labels }) {
  const selected = rule ? rule.telegram_targets : null;
  $("fp-rule-telegram-all-chats").checked = selected == null;
  const labelMap = Object.fromEntries(ids.map((id, i) => [id, labels[i] || id]));
  renderChannelPicker($("fp-rule-telegram-targets-list"), {
    selected: selected || [], available: ids, labels: labelMap,
  });
  updateTelegramTargetsVisibility();
}

/** null ("All chats") or the checked subset (possibly empty) -- always
 *  read fresh at save time, the same full-replace posture the main channel
 *  picker's own readChannelPicker() already has. */
export function readTelegramTargetsSelection() {
  if ($("fp-rule-telegram-all-chats").checked) return null;
  return readChannelPicker($("fp-rule-telegram-targets-list"));
}
