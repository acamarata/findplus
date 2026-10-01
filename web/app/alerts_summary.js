/*
 * Alerts tab: the "where alerts go" strip at the top.
 *
 * Purpose    : The Alerts tab is long (three channels, rules, a log). This strip
 *              says at a glance which channels are connected and how many rules
 *              exist, and each chip jumps to its section.
 * Inputs     : setChannelState(channels) from alerts_channels.js's loadChannels();
 *              setRuleCount(n) from alerts_rules.js's loadRules().
 * Outputs    : Buttons inside #fp-alerts-summary.
 * Constraints: textContent only. Nothing here is saved; purge() empties it.
 */
"use strict";

import { $ } from "./state.js";
import { t, plural } from "./i18n.js";

const CHANNELS = [
  ["telegram", "fp-telegram-section"],
  ["webhook", "fp-webhook-section"],
  ["whatsapp", "fp-whatsapp-section"],
];
let channelState = null;
let ruleCount = null;

function chip(text, targetId, tone) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "fp-summary-chip";
  if (tone) btn.dataset.tone = tone;
  btn.textContent = text;
  btn.addEventListener("click", () => {
    const target = $(targetId);
    if (!target) return;
    target.scrollIntoView({ block: "start" });
    const field = target.querySelector("input, button");
    if (field) field.focus({ preventScroll: true });
  });
  return btn;
}

function render() {
  const host = $("fp-alerts-summary");
  if (!host) return;
  if (channelState === null && ruleCount === null) return host.replaceChildren();
  const items = CHANNELS.map(([id, section]) => {
    const on = Boolean(channelState && channelState[id] && channelState[id].configured);
    const name = t(`alerts.channels.${id}`);
    return chip(t(on ? "alerts.summary.connected" : "alerts.summary.notConnected", { channel: name }),
      section, on ? "on" : "off");
  });
  if (ruleCount !== null) {
    items.push(chip(plural("alerts.summary.rules", ruleCount, { count: ruleCount }), "fp-rules-section",
      ruleCount === 0 ? "off" : "on"));
  }
  host.replaceChildren(...items);
}

export function setChannelState(channels) {
  channelState = channels;
  render();
}

export function setRuleCount(count) {
  ruleCount = count;
  render();
}

/** The lock hook. */
export function purgeSummary() {
  channelState = null;
  ruleCount = null;
  render();
}
