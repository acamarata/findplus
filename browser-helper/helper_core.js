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
