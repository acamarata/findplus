import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

function run(file, sandbox) {
  vm.runInNewContext(readFileSync(new URL(file, import.meta.url), "utf8"), sandbox);
}

test("content_begin marks the page and sends the begin message", () => {
  const sent = [];
  const attrs = {};
  const sandbox = {
    URLSearchParams,
    location: { search: "?state=abc", pathname: "/auth/google/begin", port: "8647" },
    document: { documentElement: { setAttribute: (k, v) => (attrs[k] = v) } },
    chrome: { runtime: { sendMessage: (m) => sent.push(m) } },
  };
  run("./content_begin.js", sandbox);
  assert.equal(attrs["data-findplus-helper"], "1");
  assert.equal(JSON.stringify(sent), JSON.stringify([{ type: "findplus-begin", mode: "signin", state: "abc", port: "8647" }]));
});

test("content_begin sends nothing without a state", () => {
  const sent = [];
  run("./content_begin.js", {
    URLSearchParams,
    location: { search: "", pathname: "/auth/google/begin", port: "8647" },
    document: { documentElement: { setAttribute: () => {} } },
    chrome: { runtime: { sendMessage: (m) => sent.push(m) } },
  });
  assert.equal(sent.length, 0);
});

test("unlock bridge forwards vault keys only when a pending unlock is active", () => {
  function bridgeWith(active) {
    const forwarded = [];
    let handler = null;
    const sandbox = {
      window: { addEventListener: (_e, h) => (handler = h) },
      chrome: {
        runtime: {
          sendMessage: (msg, cb) => {
            if (msg.type === "findplus-unlock-active" && cb) cb({ active });
            else forwarded.push(msg);
          },
        },
      },
    };
    run("./content_unlock_bridge.js", sandbox);
    handler({ source: sandbox.window, data: { source: "findplus-mm", method: "setVaultSharedKeys", vaultKeys: { finder_hw: [] } } });
    return forwarded;
  }
  assert.equal(JSON.stringify(bridgeWith(true)), JSON.stringify([{ type: "findplus-vault", vaultKeys: { finder_hw: [] } }]));
  assert.equal(JSON.stringify(bridgeWith(false)), "[]");
});
