/*
 * The sign-in panel: both provider cards and their flows, mounted anywhere.
 *
 * Purpose    : The one sign-in component. The setup wizard's sign-in step
 *              (setup_steps/signin.js) and Settings > Sign-in (auth.js) both
 *              mount it, so the two surfaces show the same cards, the same
 *              states and the same errors (owner request, E14 UI polish).
 * Inputs     : A host element and options: { prefix, level, withNotices,
 *              api, postJson, notices, appleExtra, onStatus }.
 * Outputs    : { google, apple, refresh(), stop(), purge() }.
 * Constraints: refresh() is generation-guarded: a GET /api/auth/status still
 *              in flight when purge() runs is dropped when it lands, so a lock
 *              can never be followed by "Signed in as ..." reappearing behind
 *              the lock screen (R-P2-8, same pattern as groups.js).
 */
"use strict";

import { el, buildGoogleCard, buildAppleCard } from "./cards.js";
import { GoogleFlow } from "./google_flow.js";
import { AppleFlow } from "./apple_flow.js";

export const GOOGLE_PROVIDER = "google-find-hub";
export const APPLE_PROVIDER = "apple-find-my";

export function mountSignInPanel(host, options) {
  const { prefix, level = 3, withNotices = false, appleExtra = null, onStatus = null } = options;
  const notices = () => options.notices() || {};
  const shape = { prefix, level, withNotices, notices: notices() };
  const googleCard = buildGoogleCard(shape);
  const appleCard = buildAppleCard(shape);
  if (appleExtra) appleCard.root.append(appleExtra);
  const grid = el("div", "fp-signin-cards");
  grid.append(googleCard.root, appleCard.root);
  host.append(grid);

  let generation = 0;
  const panel = {};
  const deps = {
    api: options.api,
    postJson: options.postJson,
    notices,
    onSettled: () => panel.refresh(),
  };
  panel.google = new GoogleFlow(googleCard, deps);
  panel.apple = new AppleFlow(appleCard, deps, appleExtra);

  /** Re-read who is signed in and repaint both cards. */
  panel.refresh = async () => {
    const mine = generation;
    const { providers } = await options.api("/api/auth/status");
    if (mine !== generation) return null;
    const list = providers || [];
    panel.google.render(list.find((p) => p.id === GOOGLE_PROVIDER));
    panel.apple.render(list.find((p) => p.id === APPLE_PROVIDER));
    if (onStatus) onStatus(list);
    return list;
  };

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
