/*
 * The Google card's state notices: signed out by Google, unlocked, switching.
 *
 * Purpose    : Three small blocks the Google card shows in some states only.
 *              "Revoked" is the action-needed state (UAT #22): Google ended the
 *              sign-in, usually after a password change, and Find+ cannot fetch
 *              anything until the person signs in again, so it gets a boxed
 *              alert with its own button instead of one muted line. "Ready"
 *              confirms the encrypted locations are unlocked. "Switch hint"
 *              says what switching accounts costs.
 * Inputs     : The card's id prefix; `renderNotices` takes the card plus the
 *              signed-in / revoked / needs-unlock facts GoogleFlow.render knows.
 * Outputs    : { revoked, revokedButton, ready, switchHint } elements, and the
 *              visibility and `data-attention` the stylesheet keys on.
 * Constraints: textContent only; every string through t().
 */
"use strict";

import { t } from "../i18n.js";
import { button, el } from "./cards.js";

/** The three notice elements, hidden until renderNotices() shows one. */
export function buildNotices(prefix) {
  const revoked = el("div", "fp-signin-attention");
  revoked.id = `${prefix}-google-revoked`;
  revoked.setAttribute("role", "alert");
  revoked.hidden = true;
  const actions = el("div", "fp-signin-actions");
  const revokedButton = button("btn fp-signin-btn", t("signin.google.revoked.button"),
    `${prefix}-google-revoked-btn`);
  actions.append(revokedButton);
  revoked.append(
    el("p", "fp-signin-attention-title", t("signin.google.revoked.title")),
    el("p", "fp-signin-how", t("signin.google.revoked.body")),
    actions
  );
  const ready = el("p", "fp-signin-how fp-signin-ready", t("signin.google.ready"));
  ready.id = `${prefix}-google-ready`;
  ready.hidden = true;
  const switchHint = el("p", "fp-signin-how", t("signin.google.switchHint"));
  switchHint.id = `${prefix}-google-switch-hint`;
  switchHint.hidden = true;
  return { revoked, revokedButton, ready, switchHint };
}

/** Show the notice that fits: revoked, locked (unlock block is its own), or ready. */
export function renderNotices(card, { signedIn, revoked, needsKey }) {
  card.revoked.hidden = !revoked;
  card.ready.hidden = !(signedIn && !needsKey);
  card.switchHint.hidden = !signedIn;
  // One attribute the stylesheet reads: what the person has to do next, if anything.
  if (revoked) card.root.dataset.attention = "reauth";
  else if (signedIn && needsKey) card.root.dataset.attention = "unlock";
  else delete card.root.dataset.attention;
}
