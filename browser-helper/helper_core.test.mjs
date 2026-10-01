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

const tab = (id) => ({ tab: { id } });
const begin = (over = {}) => ({ type: "findplus-begin", mode: "signin", state: "s1", port: "8647", ...over });

test("normalizePort falls back to 8647 for junk", () => {
  assert.equal(core.normalizePort(undefined), "8647");
  assert.equal(core.normalizePort("abc"), "8647");
  assert.equal(core.normalizePort("70000"), "8647");
  assert.equal(core.normalizePort(" 9000 "), "9000");
});

test("acceptBegin only takes the configured port from a tab", () => {
  const ok = core.acceptBegin({ msg: begin(), sender: tab(5), pending: null, configuredPort: undefined, now: 1000 });
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.pending, { mode: "signin", state: "s1", port: "8647", tabId: 5, at: 1000 });
  const wrong = core.acceptBegin({ msg: begin({ port: "9999" }), sender: tab(5), pending: null, configuredPort: "8647", now: 1 });
  assert.deepEqual(wrong, { ok: false, reason: "wrong-port" });
  const custom = core.acceptBegin({ msg: begin({ port: "9000" }), sender: tab(5), pending: null, configuredPort: "9000", now: 1 });
  assert.equal(custom.ok, true);
  assert.equal(core.acceptBegin({ msg: begin(), sender: {}, pending: null, now: 1 }).reason, "no-tab");
  assert.equal(core.acceptBegin({ msg: begin({ state: "" }), sender: tab(1), pending: null, now: 1 }).reason, "no-state");
  assert.equal(core.acceptBegin({ msg: begin({ mode: "x" }), sender: tab(1), pending: null, now: 1 }).reason, "bad-mode");
});

test("a second begin cannot clobber a live pending flow from another tab", () => {
  const pending = { mode: "signin", state: "old", port: "8647", tabId: 5, at: 1000 };
  const other = core.acceptBegin({ msg: begin({ state: "evil" }), sender: tab(9), pending, now: 2000 });
  assert.deepEqual(other, { ok: false, reason: "other-tab-pending" });
  const same = core.acceptBegin({ msg: begin({ state: "new" }), sender: tab(5), pending, now: 2000 });
  assert.equal(same.ok, true);
  assert.equal(same.pending.state, "new");
  const expired = core.acceptBegin({ msg: begin({ state: "n" }), sender: tab(9), pending, now: 1000 + core.PENDING_TTL_MS });
  assert.equal(expired.ok, true);
});

test("manifest pins the daemon port in matches and host permissions", async () => {
  const { readFileSync } = await import("node:fs");
  const m = JSON.parse(readFileSync(new URL("./manifest.json", import.meta.url), "utf8"));
  const pins = [...m.host_permissions, ...m.content_scripts[0].matches].filter((u) => u.includes("127.0.0.1"));
  assert.ok(pins.length >= 3);
  for (const u of pins) assert.match(u, /^http:\/\/127\.0\.0\.1:8647\//);
});

test("shouldRetry retries only transient failures, a bounded number of times", () => {
  assert.equal(core.shouldRetry(0, 1), true);
  assert.equal(core.shouldRetry(502, 2), true);
  assert.equal(core.shouldRetry(502, 3), false);
  assert.equal(core.shouldRetry(400, 1), false);
  assert.equal(core.shouldRetry(403, 1), false);
  assert.equal(core.shouldRetry(200, 1), false);
});
