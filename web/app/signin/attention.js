/*
 * Lost sign-in: the one entry every "sign in again" surface goes through.
 *
 * Purpose    : Spec in-app-login §6. The daemon says per provider whether it
 *              needs the person (`attention`: "reauth", "unlock" or "none" in
 *              /api/status provider_health and /api/auth/status). This module
 *              turns that into the dashboard banner's sentence and its ONE
 *              button, and starts the fix directly: Settings opens on the
 *              sign-in cards and the right flow begins (the Find+ window in the
 *              desktop app, the Chrome helper in a browser tab, the Apple
 *              sheet). It also follows the shell's `auth-attention` and
 *              `signin-apple-sheet` events.
 * Inputs     : provider_health rows; the shell's events (native_bridge.js).
 * Outputs    : attentionNotice(), fixSignin(), listenForAttention().
 * Constraints: Never acts while the app is locked: the lock screen comes
 *              first, and the banner is purged with everything else.
 */
"use strict";

import { t } from "../i18n.js";
import { state } from "../state.js";
import { listenNative } from "./native_bridge.js";

export const GOOGLE = "google-find-hub";
export const APPLE = "apple-find-my";

/** The banner for the first provider that needs the person, or null. */
export function attentionNotice(rows) {
  for (const row of rows || []) {
    const kind = row && row.attention;
    if (!kind || kind === "none") continue;
    const provider = row.name || row.id;
    if (provider === GOOGLE && kind === "unlock") {
      return { provider, kind, message: t("signin.attention.googleUnlock"),
        label: t("signin.attention.unlock") };
    }
    if (provider === GOOGLE || provider === APPLE) {
      const message = t(provider === GOOGLE ? "signin.attention.googleReauth"
        : "signin.attention.appleReauth");
      return { provider, kind: "reauth", message, label: t("signin.attention.signIn") };
    }
  }
  return null;
}

/**
 * Open Settings on the provider's card and start its fix. `kind` is
 * "reauth" (sign in again) or "unlock" (unlock Google's locations).
 */
export async function fixSignin(provider, kind) {
  if (state.locked) return;
  const settings = await import("../settings.js");
  await settings.openSettings();
  const auth = await import("../auth.js");
  const panel = auth.signInPanel();
  if (!panel || state.locked) return;
  await panel.refresh().catch(() => null);
  const key = provider === APPLE ? "apple" : "google";
  const cardEl = document.getElementById(`fp-auth-${key}-card`);
  if (cardEl) cardEl.scrollIntoView({ block: "nearest" });
  panel.fix(provider, kind);
}

/**
 * Follow the shell: the tray or a deep link asked for the Apple sheet, or a
 * provider's attention changed (`onChange` re-reads the status banner).
 */
export function listenForAttention(onChange) {
  listenNative("signin-apple-sheet", () => fixSignin(APPLE, "reauth"));
  listenNative("auth-attention", () => onChange());
}
