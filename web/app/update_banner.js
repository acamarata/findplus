/*
 * The small corner button that says an update is ready: "Restart to update".
 *
 * Purpose    : Usually Find+ installs an update by itself while nobody is using
 *              it. While someone is, this offers the restart instead of waiting.
 *              In a plain browser tab it only says a new version exists.
 * Inputs     : GET /api/update/status (updates.js), every ten minutes.
 * Outputs    : #fp-update-banner inside #app-shell (hidden with it on lock).
 * Constraints: "Later" hides it for that version until the page reloads. One
 *              timer, started once. createElement/textContent only.
 */
"use strict";

import { state } from "./state.js";
import { t } from "./i18n.js";
import { canInstall, installNow, offeredVersion, readStatus } from "./updates.js";

const REFRESH_MS = 10 * 60 * 1000;
let dismissed = null;
let started = false;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

const clear = () => document.getElementById("fp-update-banner")?.remove();

function restartButton(text) {
  const button = el("button", "btn btn-tiny", t("updates.bannerRestart"));
  button.type = "button";
  button.id = "fp-update-restart";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await installNow();
      text.textContent = t("updates.installing");
    } catch (err) {
      text.textContent = t("updates.installFailed", { message: String(err && err.message ? err.message : err) });
      button.disabled = false;
    }
  });
  return button;
}

function releaseLink(body) {
  const link = el("a", "", t("updates.bannerRelease"));
  link.href = body.release_url || "https://github.com/acamarata/findplus/releases";
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function render(body, version) {
  clear();
  const box = el("div", "fp-update-banner");
  box.id = "fp-update-banner";
  box.setAttribute("role", "status");
  box.setAttribute("aria-label", t("updates.bannerLabel"));
  const key = body.staged_version ? "updates.bannerReady" : "updates.bannerAvailable";
  const text = el("span", "", t(key, { version }));
  const later = el("button", "btn btn-tiny btn-secondary", t("updates.bannerLater"));
  later.type = "button";
  later.addEventListener("click", () => { dismissed = version; clear(); });
  const action = canInstall() ? restartButton(text) : releaseLink(body);
  box.append(text, action, later);
  (document.getElementById("app-shell") || document.body).appendChild(box);
}

/** Show, update or remove the corner button from a fresh status. */
export async function refreshUpdateBanner() {
  if (state.locked) return;
  let body;
  try {
    body = await readStatus();
  } catch (_) {
    return; // an older daemon without the route, or a moment offline: say nothing
  }
  const version = offeredVersion(body);
  // In the app a release still downloading is not actionable yet: wait for "ready".
  const actionable = canInstall() ? !!body.staged_version : !!version;
  if (!version || !actionable || dismissed === version) { clear(); return; }
  render(body, version);
}

/** Start the check once per page. */
export function startUpdateBanner() {
  if (started) return;
  started = true;
  refreshUpdateBanner();
  setInterval(refreshUpdateBanner, REFRESH_MS);
}
