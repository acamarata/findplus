/*
 * Pure helper logic, shared by the service worker and the node tests.
 *
 * No chrome.* or DOM access here: everything is a plain function of its
 * arguments, so the tests exercise the real decisions (which cookie counts,
 * which endpoint, how a body is shaped) without a browser. The service worker
 * (background.js) imports these and adds only the chrome.* glue.
 */
"use strict";

export const HELPER_VERSION = "1.1.5";
export const GOOGLE_COOKIE_DOMAIN = "accounts.google.com";
export const OAUTH_COOKIE = "oauth_token";

/** The one daemon port the helper talks to unless the person configured another. */
export const DEFAULT_PORT = "8647";
export const PORT_STORAGE_KEY = "findplus_port";
/** How long a pending begin stays valid; matches the daemon's state TTL. */
export const PENDING_TTL_MS = 600000;

/** A usable TCP port as a string, or the default when `value` is not one. */
export function normalizePort(value) {
  const text = String(value === undefined || value === null ? "" : value).trim();
  if (!/^\d{1,5}$/.test(text)) return DEFAULT_PORT;
  const n = Number(text);
  return n >= 1 && n <= 65535 ? String(n) : DEFAULT_PORT;
}

/**
 * Decide whether a begin message may become the pending flow.
 *
 * Accepted only when it came from a tab (a content script on Find+'s own begin
 * page), names the port this helper is configured for, carries a state, and
 * does not clobber a live pending flow that belongs to a different tab.
 * Returns {ok: true, pending} or {ok: false, reason}.
 */
export function acceptBegin({ msg, sender, pending, configuredPort, now }) {
  const tabId = sender && sender.tab ? sender.tab.id : undefined;
  if (tabId === undefined) return { ok: false, reason: "no-tab" };
  if (!msg || !msg.state) return { ok: false, reason: "no-state" };
  if (msg.mode !== "signin" && msg.mode !== "unlock") return { ok: false, reason: "bad-mode" };
  if (String(msg.port) !== normalizePort(configuredPort)) return { ok: false, reason: "wrong-port" };
  const live = pending && now - (pending.at || 0) < PENDING_TTL_MS;
  if (live && pending.tabId !== tabId) return { ok: false, reason: "other-tab-pending" };
  return {
    ok: true,
    pending: { mode: msg.mode, state: msg.state, port: String(msg.port), tabId, at: now },
  };
}

/** True when a pending flow exists and has not outlived its TTL. */
export function pendingIsLive(pending, now) {
  return Boolean(pending) && now - (pending.at || 0) < PENDING_TTL_MS;
}

/** Only a transient failure (network error, status 0, or a 5xx) is worth another
 *  attempt; a 4xx means the daemon refused it, and repeating cannot help. */
export function shouldRetry(status, attempt, max = 3) {
  return (status === 0 || status >= 500) && attempt < max;
}

export const RETRY_DELAY_MS = 2000;

export function baseUrl(port) {
  return `http://127.0.0.1:${port}`;
}
export function tokenEndpoint(port) {
  return `${baseUrl(port)}/api/auth/google/helper/token`;
}
export function unlockEndpoint(port) {
  return `${baseUrl(port)}/api/auth/google/helper/unlock`;
}
export function successUrl(port) {
  return `${baseUrl(port)}/auth/google/success`;
}

/** {mode, state, port} from a location-like object; mode is "unlock" on the
 *  unlock begin page, "signin" otherwise. */
export function parseBegin({ pathname = "", search = "", port = "" } = {}) {
  const params = new URLSearchParams(search);
  return {
    mode: pathname.indexOf("/unlock/") !== -1 ? "unlock" : "signin",
    state: params.get("state"),
    port: String(port || ""),
  };
}

/** True only for a freshly SET oauth_token cookie on accounts.google.com. */
export function isOauthCookieChange(change) {
  if (!change || change.removed) return false;
  const cookie = change.cookie || {};
  const domain = String(cookie.domain || "").replace(/^\./, "");
  return cookie.name === OAUTH_COOKIE && domain === GOOGLE_COOKIE_DOMAIN && Boolean(cookie.value);
}

export function tokenBody(state, oauthToken) {
  return { state, oauth_token: oauthToken };
}

/** The unlock body; vault keys are sent as a JSON string either way. */
export function unlockBody(state, vaultKeys) {
  const value = typeof vaultKeys === "string" ? vaultKeys : JSON.stringify(vaultKeys);
  return { state, vault_keys: value };
}

/** Forward vault keys to the daemon only during a pending unlock. */
export function shouldForwardVault(active, method) {
  return Boolean(active) && method === "setVaultSharedKeys";
}
