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

export async function api(path, options) {
  const res = await fetch(path, options);
  if (res.status === 401) {
    // The server refused: the app locked underneath us (idle timeout, restart,
    // or a PIN change). Show the lock screen rather than a confusing error.
    showLock();
    throw new Error("Locked");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const body = await res.json(); if (body.detail) detail = body.detail; } catch (_) {}
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
