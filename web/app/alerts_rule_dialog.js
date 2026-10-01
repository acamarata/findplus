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
import { $ } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";
import { renderChannelPicker } from "./components/channel-picker.js";
import { BASE_CHANNELS, availableChannels, connectedChannels, channelLabels, telegramTargets } from "./alerts_rule_channels.js";
import { fillLoading, fillOptions, populateRuleSelects } from "./alerts_rule_selects.js";
import { seedTelegramTargetsFields, updateTelegramTargetsVisibility } from "./alerts_rule_telegram_targets.js";
import { saveRuleWith } from "./alerts_rule_save.js";
import { refreshPreview, resetPreview, setPreviewContext } from "./alerts_rule_preview.js";

// Re-exported: alerts_rules.js's own `export { fillOptions, ... } from
// "./alerts_rule_dialog.js"` re-export list (its rows use it too) stays
// correct without knowing fillOptions now lives in alerts_rule_selects.js.
export { fillOptions, updateTelegramTargetsVisibility };

export function updateRuleTargetVisibility() {
  const isDevice = $("fp-rule-target-device").checked;
  // Editing locks both target radios (RuleUpdate cannot retarget a rule, see
  // seedRuleFields() below) -- the select showing the existing target needs
  // no "choose one" validation of its own then, only the enabled/disabled split.
  const editing = $("fp-rule-target-device").disabled;
  // UAT7 N13 (UAT6 N25 residue): both selects stay rendered at all times now
  // -- `hidden` used to collapse the unpicked one's box entirely, so the
  // Group row showed only a bare radio+label until chosen, then grew a
  // dropdown into existence the instant it was. Toggling `disabled` instead
  // keeps both boxes laid out from the first paint; a disabled select still
  // reads as "there is a control here" rather than looking unfinished.
  $("fp-rule-device").disabled = !isDevice;
  $("fp-rule-group").disabled = isDevice;
  $("fp-rule-device").required = !editing && isDevice;
  $("fp-rule-group").required = !editing && !isDevice;
}

/** null for "Add rule"; the rule row being edited otherwise (UAT U13). */
let editingRuleId = null;

/** Gates Save on the dialog's async load landing (CI 36194968013,
 *  FLAKE-EDITRULE): the first channel-picker render below is keyed off
 *  BASE_CHANNELS (no "native"), so editing a native-only rule leaves no
 *  "native" checkbox in the DOM until the Promise.all in openRuleDialog()
 *  resolves. Save clicked in that window read the picker as empty, PUT an
 *  empty channels list, and the server's 422 left the dialog open on an
 *  error the test never looked at -- not test flakiness, a real race a
 *  fast human could hit too. `ready` false disables Save and clears the
 *  marker before the dialog opens; true re-enables it once the picker's
 *  final render has landed. */
function setDialogReady(dlg, ready) {
  $("fp-rule-save").disabled = !ready;
  if (ready) dlg.dataset.fpReady = "true";
  else delete dlg.dataset.fpReady;
}

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
 * UAT6 N05 gated "native" behind window.__findplus_native (a plain browser
 * tab never sets it) so a new rule can no longer offer/preselect a channel
 * it cannot use -- but a rule saved with "native" from inside the app must
 * still be editable (renamed, retimed) from a plain browser tab too, so its
 * own already-saved channel is never silently stranded off the picker.
 * Split out of openRuleDialog() to keep that function under the PRI rule-7
 * 50-line cap.
 */
function availableIncludingRulesOwnChannels(rule, rawAvailable) {
  return rule && rule.channels.includes("native") && !rawAvailable.includes("native")
    ? [...rawAvailable, "native"]
    : rawAvailable;
}

/** The three selects' own values once `rule`'s data has landed -- pulled out
 *  of openRuleDialog() for the same 50-line-cap reason as the function above. */
function applyRuleTargetValues(rule) {
  if (!rule) return;
  $("fp-rule-place").value = rule.place_id != null ? String(rule.place_id) : "";
  $("fp-rule-device").value = rule.device_id || "";
  $("fp-rule-group").value = rule.group_id != null ? String(rule.group_id) : "";
}

/** Everything the dialog shows without a round trip, set before it opens.
 *  UAT2 U32/N7: the <h2> says which mode this is (aria-labelledby points at
 *  it). The three selects carry a "Loading…" placeholder until their data
 *  lands, rather than the dialog hanging shut on a fetch. */
function resetDialogForOpen(rule, opts) {
  resetPreview();
  showIntro(opts);
  $("fp-add-rule-dialog-title").textContent = t(rule ? "alerts.editRule" : "alerts.newRule");
  ["fp-rule-place", "fp-rule-device", "fp-rule-group"].forEach((id) => fillLoading($(id)));
  seedRuleFields(rule);
  $("fp-rule-error").textContent = "";
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
export async function openRuleDialog(rule = null, opts = {}) {
  editingRuleId = rule ? rule.id : null;
  resetDialogForOpen(rule, opts);

  // UAT2 U11: nothing pre-ticked yet -- the real default needs `connected`,
  // resolved below. Editing starts from the rule's own saved channels.
  const initialChannels = rule ? rule.channels : [];
  renderChannelPicker($("fp-rule-channels"), {
    selected: initialChannels, available: BASE_CHANNELS, labels: channelLabels(null),
  });

  const dlg = $("fp-add-rule-dialog");
  setDialogReady(dlg, false);
  dlg.showModal();
  refreshPreview();

  // In parallel, not in series: the channel list is usually already resolved,
  // and it must never add a round-trip to the time the dialog takes to open.
  const [, rawAvailable, connected, tgTargets] = await Promise.all([
    populateRuleSelects(), availableChannels(), connectedChannels(), telegramTargets(),
  ]);
  const available = availableIncludingRulesOwnChannels(rule, rawAvailable);
  applyRuleTargetValues(rule);
  // After "Add place": the new place is already chosen for them.
  if (opts.placeId != null) $("fp-rule-place").value = String(opts.placeId);
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
  // WP10 (gap-audit P13): seeded after the channel picker's own final
  // render lands -- its own visibility check reads that picker's DOM.
  seedTelegramTargetsFields(rule, tgTargets);
  setPreviewContext(connected);
  setDialogReady(dlg, true);
}
export const openAddRuleDialog = () => openRuleDialog(null);

/** The "place saved, now choose who to tell" lead-in (opts.intro), and the
 *  Cancel button reading "Skip for now" so it is plain the place stays. */
function showIntro(opts) {
  const intro = $("fp-rule-intro");
  intro.textContent = opts.intro || "";
  intro.hidden = !opts.intro;
  $("fp-rule-cancel").textContent = t(opts.intro ? "alerts.ruleSkip" : "common.cancel");
}
export const saveRule = () => saveRuleWith({ editingRuleId, connected: lastConnectedChannels });
