/*
 * Alerts tab: validating and saving the add/edit-rule dialog. Split out of
 * alerts_rule_dialog.js at the PRI rule-7 300-line file cap (the live
 * sentence, dry run and test send grew that file past it).
 *
 * Purpose    : Everything that has to be true before a rule is worth a round
 *              trip, the request body, and the POST/PUT itself.
 * Inputs     : The dialog's fields (by id) and a context from the dialog:
 *              { editingRuleId, connected } (the rule being edited or null,
 *              and the Set of connected channels or null when unknown).
 * Outputs    : saveRuleWith(ctx) -- closes the dialog and reloads the rules
 *              table on success, leaves it open with an error line otherwise.
 * Constraints: textContent only. alerts_rules.js is dynamic-imported for the
 *              reload, the same way alerts_rule_dialog.js always did, so the
 *              two never import each other statically.
 */
"use strict";
import { $ } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";
import { readChannelPicker } from "./components/channel-picker.js";
import { readTelegramTargetsSelection } from "./alerts_rule_telegram_targets.js";

/** "" -> null, so an unchosen select is not silently id 0. */
function numberOrNull(value) {
  const n = Number(value);
  return value === "" || Number.isNaN(n) || n === 0 ? null : n;
}

function buildRulePayload(channels, editingRuleId) {
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
    // WP10 (gap-audit P13): always resent, full-replace, same posture as
    // `channels` above -- null ("All chats") or the checked subset.
    telegram_targets: readTelegramTargetsSelection(),
  };
  if (!editingRuleId) {
    // RuleUpdate has no device_id/group_id field, and the dialog disables
    // both target inputs while editing to match (UAT U13).
    body.device_id = (isDevice ? $("fp-rule-device").value : "") || null;
    body.group_id = isDevice ? null : numberOrNull($("fp-rule-group").value);
  }
  return body;
}

/**
 * Everything that has to be true before saveRule() is worth a round trip.
 *
 * UAT6 N05: Save with nothing filled in used to create a live rule with an
 * empty name, targeting whichever device sorted first (the untracked
 * AirTag), on enter/exit both unset in spirit (on_enter defaults true so
 * that particular field was never the visible symptom, but a rule with
 * neither event ticked is just as dead), and channels the browser happened
 * to preselect. name/target reuse the browser's own required-field message
 * (reportValidity()); events/channels have no single native control to hang
 * a message on, so they get an inline sentence in the dialog's existing
 * error slot instead. Returns false and leaves the dialog open on any
 * failure -- saveRule() aborts there rather than reaching the server.
 */
function ruleFormIsValid() {
  const errorEl = $("fp-rule-error");
  errorEl.textContent = "";
  if (!$("fp-rule-name").reportValidity()) return false;
  // required is false on both selects while editing (updateRuleTargetVisibility()
  // above), so this is a no-op then -- RuleUpdate cannot retarget a rule anyway.
  const isDevice = $("fp-rule-target-device").checked;
  const targetEl = isDevice ? $("fp-rule-device") : $("fp-rule-group");
  if (!targetEl.reportValidity()) return false;
  if (!$("fp-rule-on-enter").checked && !$("fp-rule-on-exit").checked) {
    errorEl.textContent = t("alerts.selectAtLeastOneEvent");
    return false;
  }
  return true;
}

export async function saveRuleWith({ editingRuleId, connected: lastConnectedChannels }) {
  const dlg = $("fp-add-rule-dialog");
  if (!ruleFormIsValid()) return;
  const channels = readChannelPicker($("fp-rule-channels"));
  if (channels.length === 0) {
    $("fp-rule-error").textContent = t("alerts.selectAtLeastOneChannel");
    return;
  }
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
  const body = buildRulePayload(channels, editingRuleId);
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
