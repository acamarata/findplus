/*
 * Honesty notices: injects /api/config.notices sentences across the
 * dashboard -- the Settings dialog's Notices section plus the Alerts tab's
 * WhatsApp card, the add-rule dialog's channel notice, and the sign-in
 * panel's Chrome notice.
 *
 * Purpose    : PROMPT.md §2 invariant 4 — honesty text must be rendered
 *              verbatim, sourced from one place (honesty.py via /api/config).
 * Outputs    : textContent of eleven elements (loop2 B6: E8/E10/E13/CF-P2-19
 *              each added entries after the original six; only five still
 *              follow the #fp-notice-* id pattern the map started with --
 *              see the per-entry comments below for the rest).
 * Constraints: Called from main.js's boot chain, after refreshLockState()
 *              confirms the app is not locked (UAT2 N12) -- this module used
 *              to self-invoke at parse time, firing this GET /api/config
 *              before the lock screen had a chance to show, so every locked
 *              cold boot logged a 401. lock.js's hideLockAndRestore() also
 *              calls loadNotices() again after every unlock.
 */
"use strict";

export async function loadNotices() {
  const res = await fetch("/api/config");
  if (!res.ok) {
    // A 401 or an error used to parse as {} and blank every notice silently.
    console.error("loadNotices: /api/config returned", res.status);
    return;
  }
  const cfg = await res.json();
  const n = cfg.notices || {};
  const map = {
    "fp-notice-find-hub": n.find_hub,
    "fp-notice-apple": n.apple,
    "fp-notice-alerts-latency": n.alerts_latency,
    // The Alerts tab shows the same sentence. It is populated from here so
    // /api/config stays the single source; alerts.js only holds a
    // same-text initialisation fallback for a failed/slow /api/config.
    "fp-alerts-latency-notice": n.alerts_latency,
    // The Alerts tab's WhatsApp card: the CallMeBot relay caveat and the
    // setup instructions, both server-sourced like every other sentence.
    "fp-wa-relay-notice": n.whatsapp_relay,
    "fp-wa-instructions": n.whatsapp_setup,
    // Beside the add-rule dialog's channel checkboxes: what a native alert
    // does while the app is locked.
    "fp-alerts-locked-notice": n.alerts_locked,
    // The sign-in panel's Google card. Same server-sourced mechanism as every
    // other honesty sentence: honesty.CHROME_REQUIRED via /api/config.
    "fp-auth-chrome-notice": n.chrome_required,
    // The sign-in panel's Apple accessory-keys control (CF-P2-19): the same
    // honesty.APPLE sentence the Notices section already shows at
    // fp-notice-apple, repeated here because it explains accessory keys
    // specifically, right where a user is about to upload one.
    "fp-auth-apple-accessory-notice": n.apple,
    "fp-notice-presence-stale": n.presence_stale,
    // lock_not_encryption is NOT here: the Settings dialog renders it once,
    // beside the App lock setting (#lock-caveat, from /api/lock/requirements),
    // and the lock screen has its own copy. Listing it here too put the same
    // paragraph twice in one dialog (E1 honesty round 3 F13).
    "fp-notice-not-affiliated": n.not_affiliated,
  };
  for (const [id, text] of Object.entries(map)) {
    const el = document.getElementById(id);
    if (el && text) el.textContent = text;
  }
}
