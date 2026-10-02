/*
 * The Apple Find My card: one Connect button and a sheet.
 *
 * Purpose    : Build the Apple card for both sign-in surfaces (spec in-app-login
 *              §5): the provider name and "Connected as ..." line, a "Connected"
 *              chip, a boxed notice when Apple signed Find+ out, and one Connect
 *              button that opens the sign-in sheet (apple_sheet.js).
 * Inputs     : { prefix, level, notices, withNotices }.
 * Outputs    : { root, connect, ...sheet elements } for apple_flow.js.
 *              `button` is the sheet's Sign in button, so FlowBase's busy/idle
 *              handling applies to it.
 * Constraints: textContent only; every string from t() or /api/config. No Apple
 *              logo or wordmark: Find+ uses no Apple sign-in service.
 */
"use strict";

import { t } from "../i18n.js";
import { loadIconSprite } from "../icon_sprite.js";
import { buildAppleSheet } from "./apple_sheet.js";
import { button, card, chip, disconnectConfirmRow, el, head } from "./cards.js";

/** "Apple signed Find+ out": the boxed notice with its one button. */
function revokedBox(prefix) {
  const box = el("div", "fp-signin-attention");
  box.id = `${prefix}-apple-revoked`;
  box.hidden = true;
  const again = button("btn fp-signin-btn", t("signin.apple.revoked.button"),
    `${prefix}-apple-revoked-btn`);
  const actions = el("div", "fp-signin-actions");
  actions.append(again);
  box.append(
    el("p", "fp-signin-attention-title", t("signin.apple.revoked.title")),
    el("p", "fp-signin-how", t("signin.apple.revoked.body")),
    actions
  );
  return { revoked: box, revokedButton: again };
}

/** Connect, Use a different Apple ID, Disconnect. */
function cardActions(prefix) {
  const row = el("div", "fp-signin-actions");
  const connect = button("btn fp-signin-btn", t("signin.connect"), `${prefix}-apple-signin`);
  const change = button("btn btn-secondary", t("signin.apple.switch"), `${prefix}-apple-switch`);
  change.hidden = true;
  const disconnect = button("btn btn-secondary", t("signin.disconnect"), `${prefix}-apple-disconnect`);
  disconnect.hidden = true;
  row.append(connect, change, disconnect);
  return { actions: row, connect, change, disconnect };
}

/** The Apple Find My card. */
export function buildAppleCard({ prefix, level, notices, withNotices }) {
  loadIconSprite().catch(() => {});
  const root = card(`${prefix}-apple-card`, "apple");
  const top = head("key-round", t("signin.apple.heading"), level, `${prefix}-apple-status`);
  const how = el("p", "fp-signin-how", t("signin.apple.how"));
  const unavailable = el("p", "fp-signin-note", t("signin.apple.unavailable"));
  unavailable.id = `${prefix}-apple-unavailable`;
  unavailable.hidden = true;
  const ready = chip(`${prefix}-apple-ready`, t("signin.apple.readyChip"), "ok");
  const revoked = revokedBox(prefix);
  const acts = cardActions(prefix);
  // Card-level line for what happened after the sheet closed ("Cancelled.").
  const note = el("p", "fp-signin-how fp-signin-card-note");
  note.id = `${prefix}-apple-note`;
  note.setAttribute("role", "status");
  const disconnectConfirm = disconnectConfirmRow(prefix, "apple", t("signin.apple.disconnectConfirm"));
  const sheet = buildAppleSheet(prefix);
  root.append(top.wrap, revoked.revoked, how, unavailable, ready, acts.actions, note,
    disconnectConfirm.row, sheet.sheet);
  if (withNotices) root.append(el("p", "fp-wizard-footnote", notices.apple || ""));
  return {
    root, account: top.account, how, unavailable, ready, note, disconnectConfirm,
    ...revoked, ...acts, ...sheet,
  };
}
