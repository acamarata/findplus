/*
 * The rule dialog's live help: plain-words sentence, what is still missing, the
 * group explainer, the channel help, the 24 hour dry run and the test send.
 *
 * Purpose    : A rule is only trusted once someone has seen it work. This module
 *              keeps the sentence "Tell me on Telegram when Sam Bag leaves
 *              School." current as the form changes, lists what Save still
 *              needs, explains how a group decides, says why a channel is
 *              greyed out, shows what the rule would have sent in the last day
 *              and sends a real test message to the ticked channels.
 * Inputs     : The dialog's own fields (read by id); setPreviewContext() from
 *              alerts_rule_dialog.js for which channels are connected;
 *              POST /api/alerts/rules/dry-run, POST /api/alerts/test.
 * Outputs    : Text in #fp-rule-sentence, #fp-rule-missing, #fp-rule-group-note,
 *              #fp-rule-channels-help, #fp-rule-dryrun, #fp-rule-test-status.
 * Constraints: textContent only. A dry run reads recorded events, it sends
 *              nothing; the test button is the only thing here that sends.
 *              Honesty: the dry run says it is based on recorded events, and the
 *              alerts-latency sentence sits next to both buttons.
 */
"use strict";

import { $ } from "./state.js";
import { api } from "./api.js";
import { t, plural } from "./i18n.js";
import { readChannelPicker } from "./components/channel-picker.js";
import { groupById } from "./alerts_rule_selects.js";
import { groupNote, ruleSentence, stillNeeded } from "./alerts_rule_sentence.js";
import { friendlyErrorText } from "./alerts_delivery_errors.js";
import { formatTelegramTestResults } from "./alerts_telegram_targets.js";
import { relativeTime, absoluteTime } from "./rel_time.js";

/** Set<channel id> of connected channels, or null when unknown (dialog open). */
let connected = null;

export function setPreviewContext(connectedSet) {
  connected = connectedSet;
  refreshPreview();
}

function selectedText(select) {
  const opt = select.selectedOptions && select.selectedOptions[0];
  return opt && select.value !== "" ? opt.textContent : "";
}

/** Everything the sentence, the checklist and the dry run read off the form. */
function readForm() {
  const isGroup = $("fp-rule-target-group").checked;
  const targetSelect = isGroup ? $("fp-rule-group") : $("fp-rule-device");
  return {
    name: $("fp-rule-name").value,
    isGroup,
    who: selectedText(targetSelect),
    targetValue: targetSelect.value,
    place: selectedText($("fp-rule-place")),
    placeId: $("fp-rule-place").value,
    enter: $("fp-rule-on-enter").checked,
    exit: $("fp-rule-on-exit").checked,
    channelIds: readChannelPicker($("fp-rule-channels")),
    cooldown: Number($("fp-rule-cooldown").value) || 0,
  };
}

function setText(id, text) {
  const el = $(id);
  if (!el) return;
  el.textContent = text || "";
  if (el.hasAttribute("hidden") || el.dataset.hideWhenEmpty) el.hidden = !text;
}

function updateChannelHelp() {
  const help = $("fp-rule-channels-help");
  const connect = $("fp-rule-connect-btn");
  if (!help || !connect) return;
  const anyReal = connected && ["telegram", "webhook", "whatsapp"].some((id) => connected.has(id));
  const native = window.__findplus_native === true;
  const noneConnected = connected !== null && !anyReal && !native;
  const someGreyed = connected !== null && !noneConnected && ["telegram", "webhook", "whatsapp"].some((id) => !connected.has(id));
  help.textContent = noneConnected ? t("alerts.ruleChannelsNone") : someGreyed ? t("alerts.ruleChannelsDisabled") : "";
  help.hidden = !help.textContent;
  connect.hidden = !noneConnected;
}

/** Re-draw the sentence, the checklist and the group note from the form. */
export function refreshPreview() {
  const f = readForm();
  const channelLabels = f.channelIds.map((id) => t(`alerts.channels.${id}`));
  setText("fp-rule-sentence", ruleSentence({ ...f, channels: channelLabels }));
  const missing = stillNeeded({ ...f, channels: f.channelIds.length });
  setText("fp-rule-missing", missing.length ? t("alerts.sentence.stillNeeded", { items: missing.join(", ") }) : "");
  setText("fp-rule-group-note", f.isGroup && f.targetValue ? groupNote(groupById(f.targetValue)) : "");
  updateChannelHelp();
}

function row(entry) {
  const li = document.createElement("li");
  const when = document.createElement("time");
  when.dateTime = entry.observed_at;
  when.title = absoluteTime(entry.observed_at);
  when.textContent = relativeTime(entry.observed_at);
  li.append(`${entry.text} `, when);
  if (!entry.sends) li.append(` (${t("alerts.dryRun.held")})`);
  return li;
}

/** Show what this rule would have sent over the last 24 hours. */
export async function runDryRun() {
  const out = $("fp-rule-dryrun");
  const f = readForm();
  out.replaceChildren();
  if (!f.targetValue) return void (out.textContent = t("alerts.dryRun.needTarget"));
  out.textContent = t("alerts.dryRun.running");
  const body = {
    place_id: f.placeId ? Number(f.placeId) : null,
    on_enter: f.enter,
    on_exit: f.exit,
    cooldown_minutes: f.cooldown,
    ...(f.isGroup ? { group_id: Number(f.targetValue) } : { device_id: f.targetValue }),
  };
  try {
    const res = await api("/api/alerts/rules/dry-run", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    renderDryRun(out, res);
  } catch (err) {
    if (err.message !== "Locked") out.textContent = t("alerts.dryRun.failed", { error: err.message });
  }
}

function renderDryRun(out, res) {
  const lead = document.createElement("p");
  const basis = document.createElement("p");
  basis.className = "fp-field-hint";
  basis.textContent = t("alerts.dryRun.basis");
  if (res.rows.length === 0) {
    lead.textContent = t("alerts.dryRun.none");
    return out.replaceChildren(lead, basis);
  }
  lead.textContent = plural("alerts.dryRun.summary", res.would_send, { count: res.would_send });
  const list = document.createElement("ul");
  list.className = "fp-rule-dryrun-list";
  [...res.rows].reverse().slice(0, 8).forEach((r) => list.appendChild(row(r)));
  out.replaceChildren(lead, list, basis);
}

async function testOne(id) {
  const channel = t(`alerts.channels.${id}`);
  try {
    const res = await api("/api/alerts/test", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ channel: id }),
    });
    if (res.results) return `${channel}: ${formatTelegramTestResults(res.results)}`;
    return res.status === "sent"
      ? t("alerts.ruleTest.sent", { channel })
      : t("alerts.ruleTest.failed", { channel, error: friendlyErrorText(res.error || "", id) });
  } catch (err) {
    return t("alerts.ruleTest.failed", { channel, error: err.message });
  }
}

/** Send a real test message to every ticked, connected channel; say plainly how each went. */
export async function sendTests() {
  const status = $("fp-rule-test-status");
  const ids = readForm().channelIds;
  const testable = ids.filter((id) => id !== "native" && connected && connected.has(id));
  const lines = [];
  if (ids.includes("native")) lines.push(t("alerts.ruleTest.native"));
  if (testable.length === 0 && lines.length === 0) return void (status.textContent = t("alerts.ruleTest.none"));
  status.textContent = t("alerts.ruleTest.running");
  for (const id of testable) lines.push(await testOne(id));
  status.textContent = lines.join("\n");
}

/** Take the person to the channel set-up above the rules (the dialog covers it). */
function goConnect() {
  $("fp-add-rule-dialog").close();
  const tab = document.querySelector('button[data-tab="alerts"]');
  if (tab) tab.click();
  const section = $("fp-telegram-section");
  if (section) section.scrollIntoView({ block: "start" });
  const token = $("fp-tg-token");
  if (token) token.focus({ preventScroll: true });
}

/** Wire the dialog once (alerts.js's wireStaticControls()). */
export function wirePreview() {
  const form = $("fp-add-rule-form");
  form.addEventListener("input", refreshPreview);
  form.addEventListener("change", refreshPreview);
  $("fp-rule-dryrun-btn").addEventListener("click", runDryRun);
  $("fp-rule-test-btn").addEventListener("click", sendTests);
  $("fp-rule-connect-btn").addEventListener("click", goConnect);
  $("fp-rule-latency").textContent = t("honesty.alertsLatency");
}

/** Clear the help text between dialog opens (and on lock). */
export function resetPreview() {
  ["fp-rule-dryrun", "fp-rule-test-status", "fp-rule-intro"].forEach((id) => {
    const el = $(id);
    if (el) el.textContent = "";
  });
  const intro = $("fp-rule-intro");
  if (intro) intro.hidden = true;
}
