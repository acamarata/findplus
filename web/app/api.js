/*
 * Local API fetch wrapper.
 *
 * Purpose    : One place that talks to `/api/*` — every module calls api()/
 *              postJson() instead of using fetch() directly, so a 401
 *              (the app locked underneath us) is handled exactly once.
 * Constraints: Base URL is always "" (same-origin; the daemon serves the API
 *              from the same host:port as this page). Never targets an
 *              external domain.
 */
"use strict";

import { showLock } from "./lock.js";

/** Renders a FastAPI error body's `detail` as a string.
 *
 * A validation failure (422) sends `detail` as a list of
 * `{loc, msg, type}` objects, not a string — passed straight to `Error()`
 * that stringifies to the useless `[object Object]`. Every other error
 * shape (`detail` already a string) passes through unchanged.
 */
function formatDetail(detail) {
  if (Array.isArray(detail)) {
    return detail.map((item) => (item && item.msg) || JSON.stringify(item)).join("; ");
  }
  return detail;
}

export async function api(path, options) {
  const res = await fetch(path, options);
  if (res.status === 401) {
    // The server refused: the app locked underneath us (idle timeout, restart,
    // or a PIN change). Show the lock screen rather than a confusing error.
    // Awaited so the DOM purge it triggers finishes before this call's
    // rejection reaches its caller — never a window where a caught error is
    // handled while stale location data is still on screen.
    await showLock();
    throw new Error("Locked");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) detail = formatDetail(body.detail);
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

export function postJson(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}
