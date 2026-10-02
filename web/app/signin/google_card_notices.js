/*
 * The Google card's state notices: signed out by Google, unlocked, switching.
 *
 * Purpose    : Three small blocks the Google card shows in some states only.
 *              "Revoked" is the action-needed state (UAT #22): Google ended the
 *              sign-in, usually after a password change, and Find+ cannot fetch
 *              anything until the person signs in again, so it gets a boxed
 *              alert with its own button instead of one muted line. Two chips
 *              say whether the encrypted locations are unlocked or locked. "Switch hint"
 *              says what switching accounts costs.
 * Inputs     : The card's id prefix; `renderNotices` takes the card plus the
 *              signed-in / revoked / needs-unlock facts GoogleFlow.render knows.
 * Outputs    : { revoked, revokedButton, ready, locked, chips, switchHint }, and the
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
  const ready = el("p", "fp-signin-chip fp-signin-ready", t("signin.google.ready"));
  ready.id = `${prefix}-google-ready`;
  ready.hidden = true;
  const locked = el("p", "fp-signin-chip fp-signin-locked", t("signin.google.lockedChip"));
  locked.id = `${prefix}-google-locked`;
  locked.hidden = true;
  const switchHint = el("p", "fp-signin-how", t("signin.google.switchHint"));
  switchHint.id = `${prefix}-google-switch-hint`;
  switchHint.hidden = true;
  const chips = el("div", "fp-signin-chips");
  chips.append(ready, locked);
  return { revoked, revokedButton, ready, locked, chips, switchHint };
}

/**
 * Show the notice that fits: revoked, locked (the unlock block is its own), or
 * ready. `attention` is the daemon's word for a lost sign-in (contract §4).
 */
export function renderNotices(card, { signedIn, revoked, needsKey, attention }) {
  if (attention === "reauth") revoked = true;
  if (attention === "unlock" && signedIn) needsKey = true;
  card.revoked.hidden = !revoked;
  const live = signedIn && !revoked;
  card.ready.hidden = !(live && !needsKey);
  card.locked.hidden = !(live && needsKey);
  card.switchHint.hidden = !live;
  // One attribute the stylesheet reads: what the person has to do next, if anything.
  if (revoked) card.root.dataset.attention = "reauth";
  else if (live && needsKey) card.root.dataset.attention = "unlock";
  else delete card.root.dataset.attention;
}
