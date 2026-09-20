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
    return detail.map(formatValidationItem).join("; ");
  }
  return detail;
}

/** "radius_meters: Input should be greater than 0" — the field, then the reason.
 *
 * The message alone ("Field required", "Input should be...") does not say
 * which of a dialog's seven inputs is wrong, so the user has nothing to act
 * on. FastAPI puts the field in `loc` as ["body", "<field>"]; "body" is
 * dropped because every one of these errors is about the body.
 */
function formatValidationItem(item) {
  if (!item || !item.msg) return JSON.stringify(item);
  const where = (item.loc || []).filter((p) => p !== "body").join(".");
  return where ? `${where}: ${item.msg}` : item.msg;
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
  // A 204 has no body, and res.json() on an empty body rejects with a parse
  // error that reads like a server failure. Every DELETE route in this API
  // answers 204, which is why places.js and alerts_rules.js reach past this
  // wrapper to a raw fetch() — and lose the 401 lock handling with it.
  if (res.status === 204) return null;
  return res.json();
}

export function postJson(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}
