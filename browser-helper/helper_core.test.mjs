import { test } from "node:test";
import assert from "node:assert/strict";
import * as core from "./helper_core.js";

test("parseBegin reads mode, state and port", () => {
  assert.deepEqual(core.parseBegin({ pathname: "/auth/google/begin", search: "?state=abc", port: "8647" }),
    { mode: "signin", state: "abc", port: "8647" });
  assert.deepEqual(core.parseBegin({ pathname: "/auth/google/unlock/begin", search: "?state=z", port: "9000" }),
    { mode: "unlock", state: "z", port: "9000" });
  assert.equal(core.parseBegin({ pathname: "/auth/google/begin", search: "" }).state, null);
});

test("isOauthCookieChange only accepts a fresh oauth_token on accounts.google.com", () => {
  const ok = { removed: false, cookie: { name: "oauth_token", domain: "accounts.google.com", value: "oauth2_4/x" } };
  assert.equal(core.isOauthCookieChange(ok), true);
  assert.equal(core.isOauthCookieChange({ ...ok, removed: true }), false);
  assert.equal(core.isOauthCookieChange({ removed: false, cookie: { name: "oauth_token", domain: "accounts.google.com", value: "" } }), false);
  assert.equal(core.isOauthCookieChange({ removed: false, cookie: { name: "SID", domain: "accounts.google.com", value: "y" } }), false);
  assert.equal(core.isOauthCookieChange({ removed: false, cookie: { name: "oauth_token", domain: "evil.example", value: "y" } }), false);
  // a leading-dot domain still counts
  assert.equal(core.isOauthCookieChange({ removed: false, cookie: { name: "oauth_token", domain: ".accounts.google.com", value: "y" } }), true);
});

test("bodies and endpoints", () => {
  assert.deepEqual(core.tokenBody("s", "t"), { state: "s", oauth_token: "t" });
  assert.deepEqual(core.unlockBody("s", { finder_hw: [] }), { state: "s", vault_keys: '{"finder_hw":[]}' });
  assert.deepEqual(core.unlockBody("s", "raw"), { state: "s", vault_keys: "raw" });
  assert.equal(core.tokenEndpoint("8647"), "http://127.0.0.1:8647/api/auth/google/helper/token");
  assert.equal(core.unlockEndpoint("8647"), "http://127.0.0.1:8647/api/auth/google/helper/unlock");
  assert.equal(core.successUrl("8647"), "http://127.0.0.1:8647/auth/google/success");
});

test("shouldForwardVault only when active and the right method", () => {
  assert.equal(core.shouldForwardVault(true, "setVaultSharedKeys"), true);
  assert.equal(core.shouldForwardVault(false, "setVaultSharedKeys"), false);
  assert.equal(core.shouldForwardVault(true, "closeView"), false);
});
