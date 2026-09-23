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

/**
 * Tag a thrown error with the HTTP status that caused it.
 *
 * Callers that need to tell one failure from another read `err.status` rather
 * than matching on the message text. main.js's onboarding check needs it: a
 * 401 there means "locked, leave it to the lock screen", and every other
 * status is a real error that must not be swallowed.
 */
function withStatus(error, status) {
  error.status = status;
  return error;
}

/** The response body's `detail`, formatted, or `fallback` if there is none. */
async function _detailOr(res, fallback) {
  try {
    const payload = await res.json();
    if (payload && payload.detail) return formatDetail(payload.detail);
  } catch (_) {}
  return fallback;
}

export async function api(path, options) {
  // skipLock: the unlock route itself answers 401 for a WRONG PIN, not for
  // "the app locked underneath us" — showLock() is redundant there (the lock
  // screen is already up) and it would discard the real "Incorrect PIN..."
  // detail in favour of the generic "Locked" message (UAT U20). Stripped
  // before the options object reaches fetch().
  const { skipLock, ...fetchOptions } = options || {};
  const res = await fetch(path, fetchOptions);
  if (res.status === 401 && skipLock) {
    throw withStatus(new Error(await _detailOr(res, "Locked")), 401);
  }
  if (res.status === 401) {
    // The server refused: the app locked underneath us (idle timeout, restart,
    // or a PIN change). Show the lock screen rather than a confusing error.
    // Awaited so the DOM purge it triggers finishes before this call's
    // rejection reaches its caller — never a window where a caught error is
    // handled while stale location data is still on screen.
    await showLock();
    throw withStatus(new Error("Locked"), 401);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    let payload = null;
    try {
      payload = await res.json();
      if (payload && payload.detail) detail = formatDetail(payload.detail);
    } catch (_) {}
    const error = withStatus(new Error(detail), res.status);
    // The sign-in routes answer 409 with the job_id of the run already in
    // progress. Dropping the body left a caller able to report the conflict
    // and nothing else; carrying it lets the caller rejoin that job.
    error.body = payload;
    throw error;
  }
  // A 204 has no body, and res.json() on an empty body rejects with a parse
  // error that reads like a server failure. Every DELETE route in this API
  // answers 204 (loop2 B4: places.js and alerts_channels.js's
  // clearTelegramChannel()/removeWebhook() used to reach past this wrapper
  // to a raw fetch() and lose the 401 lock handling with it; both are fixed).
  if (res.status === 204) return null;
  return res.json();
}

export function postJson(path, body, options) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
    ...options,
  });
}
