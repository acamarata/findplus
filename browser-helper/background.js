/*
 * Find+ helper service worker.
 *
 * It does exactly two things, and only while Find+ (on this same computer)
 * has told it to via a begin page it served:
 *  - sign-in: when Google sets the `oauth_token` cookie on accounts.google.com,
 *    hand that one value to Find+ on 127.0.0.1 and move the tab to the success
 *    page. Find+ exchanges it and never stores it.
 *  - unlock: relay the end-to-end vault keys the Google unlock page produces to
 *    Find+ on 127.0.0.1.
 * It never talks to any host other than accounts.google.com and 127.0.0.1
 * (see host_permissions), keeps no history, and sends nothing anywhere else.
 */
import {
  HELPER_VERSION,
  PORT_STORAGE_KEY,
  acceptBegin,
  isOauthCookieChange,
  successUrl,
  tokenBody,
  tokenEndpoint,
  unlockBody,
  unlockEndpoint,
} from "./helper_core.js";

const PENDING_KEY = "findplus_pending";

async function getPending() {
  const stored = await chrome.storage.session.get(PENDING_KEY);
  return stored[PENDING_KEY] || null;
}
async function setPending(pending) {
  await chrome.storage.session.set({ [PENDING_KEY]: pending });
}
async function clearPending() {
  await chrome.storage.session.remove(PENDING_KEY);
}

/** The daemon port this helper was configured for (default 8647). */
async function configuredPort() {
  try {
    const stored = await chrome.storage.local.get(PORT_STORAGE_KEY);
    return stored[PORT_STORAGE_KEY];
  } catch (_err) {
    return undefined;
  }
}

async function postJson(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.ok;
  } catch (_err) {
    return false;
  }
}

async function moveTabToSuccess(port) {
  const tabs = await chrome.tabs.query({ url: "https://accounts.google.com/*" });
  const tab = tabs[0];
  if (tab && tab.id !== undefined) {
    try {
      await chrome.tabs.update(tab.id, { url: successUrl(port) });
    } catch (_err) {
      /* the tab may be gone; the daemon already has the value */
    }
  }
}

chrome.cookies.onChanged.addListener(async (change) => {
  if (!isOauthCookieChange(change)) return;
  const pending = await getPending();
  if (!pending || pending.mode !== "signin") return;
  const ok = await postJson(tokenEndpoint(pending.port), tokenBody(pending.state, change.cookie.value));
  if (ok) {
    await clearPending();
    await moveTabToSuccess(pending.port);
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg && msg.type === "findplus-begin") {
      const verdict = acceptBegin({
        msg,
        sender,
        pending: await getPending(),
        configuredPort: await configuredPort(),
        now: Date.now(),
      });
      if (verdict.ok) await setPending(verdict.pending);
      sendResponse({ ok: verdict.ok, version: HELPER_VERSION });
      return;
    }
    if (msg && msg.type === "findplus-unlock-active") {
      const pending = await getPending();
      const active = Boolean(pending && pending.mode === "unlock");
      sendResponse({ active });
      return;
    }
    if (msg && msg.type === "findplus-vault") {
      const pending = await getPending();
      if (pending && pending.mode === "unlock") {
        const ok = await postJson(unlockEndpoint(pending.port), unlockBody(pending.state, msg.vaultKeys));
        if (ok) {
          await clearPending();
          await moveTabToSuccess(pending.port);
        }
      }
      sendResponse({ ok: true });
      return;
    }
  })();
  return true; // keep the message channel open for the async sendResponse
});
