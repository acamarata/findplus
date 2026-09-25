/*
 * Settings > Sign-in: Google Find Hub and Apple Find My.
 *
 * Purpose    : Sign in to either provider from the dashboard instead of only
 *              from `findplus auth` in a terminal (D-P2-6). The panel is the
 *              first section of the Settings dialog (ruling R-P2-8); its cards
 *              are the shared sign-in component (signin/panel.js), the same
 *              one the setup wizard's sign-in step mounts.
 * Inputs     : GET /api/auth/status and the sign-in job routes, all through
 *              signin/*. Accessory-key registration (POST
 *              /api/apple/accessories) is auth_accessories.js; its static
 *              block in web/partials/settings.html is moved into the Apple
 *              card here and hidden with it when the Apple extra is missing.
 * Outputs    : The two provider cards inside #fp-auth-cards.
 * Constraints: Every visible string goes through t(); the Chrome honesty
 *              sentence comes from /api/config, never typed here (PROMPT.md
 *              §2 invariant 4). Settings already has a Notices section, so the
 *              per-provider honesty sentences are not repeated in the cards.
 */
"use strict";

import { $, state } from "./state.js";
import { api, postJson } from "./api.js";
import { loadCatalog } from "./i18n.js";
import { mountAccessoriesPanel, purgeAccessories } from "./auth_accessories.js";
import { mountSignInPanel } from "./signin/panel.js";

/** The mounted panel, built once; a reopen only re-reads the status. */
let panel = null;

/** The live panel, for tests that drive a state directly. */
export function signInPanel() {
  return panel;
}

/** Both provider cards, from one GET /api/auth/status. */
export async function loadAuthStatus() {
  if (panel) await panel.refresh();
}

/**
 * Build the panel once and read the current status (ruling R-P2-8).
 *
 * `root` is #fp-settings-signin. settings.js calls this again every time the
 * dialog opens; only the status is re-read, so a sign-in finished in the
 * wizard or another tab shows up on the next open.
 */
export function mountAuthPanel(root, { refresh = true } = {}) {
  if (!root) return;
  if (!panel) {
    panel = mountSignInPanel($("fp-auth-cards") || root, {
      prefix: "fp-auth",
      level: 4,
      api,
      postJson,
      notices: () => state.config && state.config.notices,
      appleExtra: $("fp-auth-apple-accessories"),
    });
    mountAccessoriesPanel();
  }
  // Locked or unreachable: the lock screen is already up and there is nothing
  // to render, exactly as alerts.js treats its own first load.
  if (refresh) loadAuthStatus().catch(() => {});
}

/**
 * lock.js purgeRenderedData() hook: no account survives the lock screen.
 *
 * The Settings dialog keeps its content when it closes, so "Signed in as ...",
 * a typed Apple ID and an unsent password would all still be readable behind
 * the lock screen (PROMPT.md §2: purge destroys, never hides). panel.purge()
 * also drops any status or progress response still in flight.
 */
export function purge() {
  if (panel) panel.purge();
  purgeAccessories();
}

/**
 * Build the panel at page load, without reading status.
 *
 * The panel lives inside a closed dialog, so a GET /api/auth/status here buys
 * nothing and costs a request on the boot path. settings.js asks for the
 * status when the dialog opens, the first moment anyone can see it.
 */
export async function init() {
  await loadCatalog();
  mountAuthPanel($("fp-settings-signin"), { refresh: false });
}

init();
