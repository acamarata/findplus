/*
 * The sign-in panel: both provider cards and their flows, mounted anywhere.
 *
 * Purpose    : The one sign-in component. The setup wizard's sign-in step
 *              (setup_steps/signin.js) and Settings > Sign-in (auth.js) both
 *              mount it, so the two surfaces show the same cards, the same
 *              states and the same errors (owner request, E14 UI polish).
 * Inputs     : A host element and options: { prefix, level, withNotices,
 *              api, postJson, notices, appleExtra, onStatus }.
 * Outputs    : { google, apple, refresh(), fix(provider, kind), stop(), purge() }.
 * Constraints: refresh() is generation-guarded: a GET /api/auth/status still
 *              in flight when purge() runs is dropped when it lands, so a lock
 *              can never be followed by "Signed in as ..." reappearing behind
 *              the lock screen (R-P2-8, same pattern as groups.js).
 */
"use strict";

import { el, notAffiliatedFooter } from "./cards.js";
import { buildAppleCard } from "./apple_card.js";
import { buildGoogleCard } from "./google_card.js";
import { hasNativeWindow } from "./native_bridge.js";
import { GoogleFlow } from "./google_flow.js";
import { AppleFlow } from "./apple_flow.js";

export const GOOGLE_PROVIDER = "google-find-hub";
export const APPLE_PROVIDER = "apple-find-my";

/**
 * Build both cards and mount them plus the shared honesty footer.
 *
 * UAT7-N17: the "not affiliated" sentence used to print inside each card;
 * one copy under the grid instead, so the pair says it once per surface.
 */
function mountCards(host, shape, appleExtra) {
  const googleCard = buildGoogleCard(shape);
  const appleCard = buildAppleCard(shape);
  if (appleExtra) appleCard.root.append(appleExtra);
  const grid = el("div", "fp-signin-cards");
  grid.append(googleCard.root, appleCard.root);
  host.append(grid, notAffiliatedFooter(shape.prefix, shape.notices));
  return { googleCard, appleCard };
}

/**
 * A lost sign-in's one tap (dashboard banner, tray, deep link): start the
 * fix straight away. `kind` is the daemon's attention word (contract §4).
 */
function startFix(panel, provider, kind) {
  if (provider === APPLE_PROVIDER) return panel.apple.open();
  if (kind === "unlock") return panel.google.unlockAgain();
  return panel.google.signInAgain();
}

/**
 * After a sign-in, an unlock or a disconnect: re-read and tell the dashboard
 * (live_refresh.js listens), since that changes what the next poll can do.
 */
function settled(panel) {
  return panel.refresh().then((list) => {
    if (list) window.dispatchEvent(new CustomEvent("findplus:accounts-changed"));
    return list;
  });
}

export function mountSignInPanel(host, options) {
  const { prefix, level = 3, withNotices = false, appleExtra = null, onStatus = null } = options;
  const notices = () => options.notices() || {};
  // The desktop app's bridge decides the Google card's lead: Connect (the
  // Find+ window) there, the Chrome helper in a plain browser tab.
  const shape = { prefix, level, withNotices, notices: notices(), native: hasNativeWindow() };
  const { googleCard, appleCard } = mountCards(host, shape, appleExtra);

  let generation = 0;
  const panel = {};
  const deps = { api: options.api, postJson: options.postJson, notices,
    onSettled: () => settled(panel) };
  panel.google = new GoogleFlow(googleCard, deps);
  panel.apple = new AppleFlow(appleCard, deps, appleExtra);

  /** Re-read who is signed in and repaint both cards. */
  panel.refresh = async () => {
    const mine = generation;
    const status = await options.api("/api/auth/status");
    if (mine !== generation) return null;
    const list = status.providers || [];
    panel.google.render(list.find((p) => p.id === GOOGLE_PROVIDER));
    panel.google.setHelperInstalled(!!status.google_helper_installed);
    panel.google.setNative(status.google_native);
    panel.apple.render(list.find((p) => p.id === APPLE_PROVIDER));
    if (onStatus) onStatus(list);
    return list;
  };

  panel.fix = (provider, kind) => startFix(panel, provider, kind);
  /** Stop both polls; what is on screen stays (Back, a re-render). */
  panel.stop = () => {
    generation++;
    panel.google.stop();
    panel.apple.stop();
  };

  /** Lock purge: every account, typed value and message goes. */
  panel.purge = () => {
    generation++;
    panel.google.purge();
    panel.apple.purge();
  };
  return panel;
}
