/*
 * Honesty notices: injects the six /api/config.notices sentences into the
 * Settings dialog's Notices section.
 *
 * Purpose    : PROMPT.md §2 invariant 4 — honesty text must be rendered
 *              verbatim, sourced from one place (honesty.py via /api/config).
 * Outputs    : textContent of the six #fp-notice-* elements.
 * Constraints: Module scripts are deferred, so the DOM is ready when this
 *              runs; no DOMContentLoaded hook or caller is needed.
 */
"use strict";

export async function loadNotices() {
  const cfg = await fetch("/api/config").then((r) => r.json());
  const n = cfg.notices || {};
  const map = {
    "fp-notice-find-hub": n.find_hub,
    "fp-notice-apple": n.apple,
    "fp-notice-alerts-latency": n.alerts_latency,
    // The Alerts tab shows the same sentence. It is populated from here so
    // /api/config stays the single source; alerts.js only holds a
    // same-text initialisation fallback for a failed/slow /api/config.
    "fp-alerts-latency-notice": n.alerts_latency,
    "fp-notice-presence-stale": n.presence_stale,
    "fp-notice-lock": n.lock_not_encryption,
    "fp-notice-not-affiliated": n.not_affiliated,
  };
  for (const [id, text] of Object.entries(map)) {
    const el = document.getElementById(id);
    if (el && text) el.textContent = text;
  }
}

loadNotices().catch(() => {});
