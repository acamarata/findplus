/*
 * The Find+ begin page's own script (served at /auth/google/begin and the
 * unlock begin page). It waits briefly for the Find+ helper extension to mark
 * the page. If the helper is there, it reports that to Find+ and lets the page
 * continue to Google. If not, it shows the one-time install steps instead. The
 * helper, the state and the redirect target all come from the page the daemon
 * served; this script adds no secrets of its own.
 */
"use strict";

const root = document.querySelector("[data-fp-begin]");
const waitLine = root ? root.querySelector("[data-fp-wait]") : null;
const install = root ? root.querySelector("[data-fp-install]") : null;
const target = root ? root.dataset.fpTarget : "";
const state = root ? root.dataset.fpState : "";

const DEADLINE_MS = 2000;
const POLL_MS = 100;

function helperPresent() {
  return document.documentElement.hasAttribute("data-findplus-helper");
}

async function reportSeen() {
  try {
    await fetch("/api/auth/google/helper/seen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: state || "" }),
    });
  } catch (_err) {
    /* best-effort: the card also learns the helper is present from the begin message */
  }
}

function showInstall() {
  if (install) install.hidden = false;
  if (waitLine) waitLine.hidden = true;
}

async function proceed() {
  await reportSeen();
  if (target) window.location.href = target;
}

function start() {
  if (!root) return;
  const started = Date.now();
  const timer = setInterval(() => {
    if (helperPresent()) {
      clearInterval(timer);
      proceed();
    } else if (Date.now() - started >= DEADLINE_MS) {
      clearInterval(timer);
      showInstall();
    }
  }, POLL_MS);
}

start();
