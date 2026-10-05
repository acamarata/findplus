/*
 * Alerts tab: the Channels section, one compact row per channel.
 *
 * Purpose    : Telegram, Webhook and WhatsApp each show as a row (name, connected
 *              or not, a Connect/Edit button). The set-up form sits inside the row
 *              and stays folded until it is asked for, so Rules stay near the top.
 *              Controls that only make sense once a channel is connected (send a
 *              test, clear, add chats) carry `data-needs-connection` and are hidden,
 *              not greyed out, until then (alerts.css).
 * Inputs     : setChannelState(channels) from alerts_channels.js's loadChannels()
 *              ({ telegram|webhook|whatsapp: { configured } }, or null on lock).
 * Outputs    : data-connected on each `.fp-channel`, the status text and the row
 *              button inside it. openChannel(id) unfolds a form and focuses it.
 * Constraints: textContent only. Nothing here is saved; purgeChannelRows() folds
 *              everything and forgets the state.
 */
"use strict";

import { $ } from "./state.js";
import { t } from "./i18n.js";

const CHANNELS = ["telegram", "webhook", "whatsapp"];
let channelState = null;

function rowParts(id) {
  const root = $(`fp-${id}-section`);
  return root && {
    root,
    body: $(`fp-${id}-body`),
    state: root.querySelector("[data-channel-state]"),
    button: root.querySelector("[data-channel-toggle]"),
  };
}

function paintButton(id, parts) {
  const name = t(`alerts.channels.${id}`);
  const open = !parts.body.hidden;
  const connected = parts.root.dataset.connected === "true";
  const key = open ? "hide" : connected ? "edit" : "connect";
  parts.button.textContent = t(`alerts.channelRow.${key}`);
  parts.button.setAttribute("aria-label", t(`alerts.channelRow.${key}Aria`, { channel: name }));
  parts.button.setAttribute("aria-expanded", String(open));
}

function paintRow(id) {
  const parts = rowParts(id);
  if (!parts) return;
  const on = Boolean(channelState && channelState[id] && channelState[id].configured);
  parts.root.dataset.connected = String(on);
  parts.state.textContent = t(on ? "alerts.channelRow.connected" : "alerts.channelRow.notConnected");
  paintButton(id, parts);
}

/** Unfold (or fold) one channel's form; focus stays on the row's button. */
export function setChannelOpen(id, open) {
  const parts = rowParts(id);
  if (!parts) return;
  parts.body.hidden = !open;
  paintButton(id, parts);
}

/** Unfold a channel's form, bring its row into view and, when it is not connected
 *  yet, focus its first field (rule dialog "Connect a channel", #alerts-webhook).
 *  A connected form is left unfocused: its token field is masked and clears on focus. */
export function openChannel(id) {
  setChannelOpen(id, true);
  const parts = rowParts(id);
  if (!parts) return;
  parts.root.scrollIntoView({ block: "start" });
  const field = parts.root.dataset.connected === "false" && parts.body.querySelector("input");
  if (field) field.focus({ preventScroll: true });
}

/** Wire each row's button once (alerts.js's wireStaticControls()). */
export function wireChannelRows() {
  CHANNELS.forEach((id) => {
    const parts = rowParts(id);
    if (!parts) return;
    parts.button.addEventListener("click", () => setChannelOpen(id, parts.body.hidden));
    paintRow(id);
  });
}

export function setChannelState(channels) {
  channelState = channels;
  CHANNELS.forEach(paintRow);
}

/** The lock hook: forget the state and fold every form. */
export function purgeChannelRows() {
  channelState = null;
  CHANNELS.forEach((id) => {
    const parts = rowParts(id);
    if (parts) parts.body.hidden = true;
    paintRow(id);
  });
}
