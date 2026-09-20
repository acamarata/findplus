/*
 * Sign-in panel: Google Find Hub and Apple Find My.
 *
 * Purpose    : Sign in to either provider from the dashboard instead of only
 *              from `findplus auth` in a terminal (D-P2-6). The panel is the
 *              first section of the Settings dialog (ruling R-P2-8), markup in
 *              web/partials/settings.html.
 * Inputs     : GET /api/auth/status, POST /api/auth/google/start,
 *              GET /api/auth/google/progress, POST /api/auth/apple/start,
 *              POST /api/auth/apple/code.
 * Outputs    : The two provider cards inside #fp-settings-signin.
 * Constraints: textContent only, never raw markup — a status line comes from
 *              the API and can never run as script. The Apple password and the
 *              2FA code are cleared from their inputs the moment the request is
 *              sent, success or failure, matching settings.js's PIN fields.
 *              Every visible string goes through t(); the Chrome honesty
 *              sentence is injected by notices.js from /api/config, never typed
 *              here (PROMPT.md §2 invariant 4).
 */
"use strict";

import { $, showAlert } from "./state.js";
import { api, postJson } from "./api.js";
import { t, loadCatalog } from "./i18n.js";

const GOOGLE_PROVIDER = "google-find-hub";
const APPLE_PROVIDER = "apple-find-my";
/** The same 2 s cadence main.js:153 already uses for the map refresh. */
const POLL_INTERVAL_MS = 2000;
/** States in which a second "Sign in with Google" click would 409. */
const BUSY_STATES = ["launching", "waiting_for_user", "capturing"];

/** Set once mountAuthPanel() has wired the buttons, so a reopen only reloads. */
let mounted = false;
/** The Apple job awaiting its 2FA code, or null. */
let appleJobId = null;

/** Both provider cards, from one GET /api/auth/status. */
export async function loadAuthStatus() {
  const { providers } = await api("/api/auth/status");
  const google = providers.find((p) => p.id === GOOGLE_PROVIDER);
  const apple = providers.find((p) => p.id === APPLE_PROVIDER);
  // A provider the daemon does not offer (the Apple extra is not installed)
  // has no card to fill; rendering `undefined` would throw past init().
  if (google) renderGoogleCard(google);
  if (apple) renderAppleCard(apple);
}

/** Google card: who is signed in, and whether the button is still offered. */
export function renderGoogleCard(p) {
  $("fp-auth-google-status").textContent = p.signed_in
    ? t("auth.status.signed_in", { account: p.account })
    : t("auth.status.not_signed_in");
  $("fp-auth-google-signin").disabled = p.signed_in;
}

/** Apple card: same status line, plus the credentials form when signed out. */
export function renderAppleCard(p) {
  $("fp-auth-apple-status").textContent = p.signed_in
    ? t("auth.status.signed_in", { account: p.account })
    : t("auth.status.not_signed_in");
  $("fp-auth-apple-form").classList.toggle("hidden", !!p.signed_in);
}

/**
 * The one place the Chrome download link is revealed.
 *
 * Called from renderGoogleProgress() and from startGoogleSignIn()'s 400
 * branch, so the link is never left permanently on screen for someone who
 * does have Chrome.
 */
function showChromeMissing(message) {
  const progress = $("fp-auth-google-progress");
  progress.textContent = message;
  progress.classList.remove("hidden");
  $("fp-auth-chrome-download").classList.remove("hidden");
  $("fp-auth-google-signin").disabled = true;
}

/** The catalog line for a job state, or "" for a state with nothing to say. */
function googleProgressText(progress) {
  switch (progress.state) {
    case "launching":
      return t("auth.google.launching");
    case "waiting_for_user":
      return t("auth.google.waiting");
    case "capturing":
      return t("auth.google.capturing");
    case "failed":
      return progress.message;
    default:
      return "";
  }
}

/** One poll's `{state, message, chrome_found}` rendered onto the Google card. */
export function renderGoogleProgress(progress) {
  if (!progress.chrome_found) {
    showChromeMissing(t("auth.google.chrome_missing"));
    return;
  }
  $("fp-auth-chrome-download").classList.add("hidden");
  const el = $("fp-auth-google-progress");
  const text = googleProgressText(progress);
  el.textContent = text;
  el.classList.toggle("hidden", !text);
  $("fp-auth-google-signin").disabled = BUSY_STATES.includes(progress.state);
}

/**
 * Start the Chrome flow, then poll it.
 *
 * A 400 for a missing Chrome never starts a poll: api() throws the route's
 * `detail`, which is byte-identical to the `auth.google.chrome_missing`
 * catalog value (both are honesty.CHROME_REQUIRED, ruling R-P2-6).
 */
async function startGoogleSignIn() {
  try {
    const { job_id } = await api("/api/auth/google/start", { method: "POST" });
    pollGoogleProgress(job_id);
  } catch (err) {
    if (err.message === t("auth.google.chrome_missing")) {
      showChromeMissing(err.message);
    } else if (err.message !== "Locked") {
      showAlert(err.message, "err");
    }
  }
}

/**
 * Poll one Google job until it settles, then refresh the cards.
 *
 * A stacked second poll cannot happen: a running job 409s
 * startGoogleSignIn(), which surfaces through showAlert rather than starting
 * another interval.
 */
export function pollGoogleProgress(jobId) {
  const timer = setInterval(async () => {
    try {
      const progress = await api("/api/auth/google/progress?job_id=" + jobId);
      renderGoogleProgress(progress);
      if (["done", "failed"].includes(progress.state)) {
        clearInterval(timer);
        await loadAuthStatus();
      }
    } catch (_) {
      // A transient failure is a skipped tick, not a dead poll; a job that
      // really is gone answers 404 forever and the user can start again.
    }
  }, POLL_INTERVAL_MS);
}

/** Show or hide the 2FA code row. */
export function showApple2fa(show) {
  $("fp-auth-apple-2fa").classList.toggle("hidden", !show);
}

/** Apple ID + password -> a job awaiting the code from the trusted device. */
async function submitAppleSignIn() {
  const apple_id = $("fp-auth-apple-id").value.trim();
  const password = $("fp-auth-apple-password").value;
  try {
    const { job_id } = await api("/api/auth/apple/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apple_id, password }),
    });
    appleJobId = job_id;
    showApple2fa(true);
  } catch (err) {
    if (err.message !== "Locked") showAlert(err.message, "err");
  } finally {
    // The password leaves the DOM whatever happened, the same way
    // settings.js never leaves a PIN sitting in its field.
    $("fp-auth-apple-password").value = "";
  }
}

/** The 2FA code; on success the cards reload and the code row hides again. */
async function submitAppleCode() {
  try {
    await postJson("/api/auth/apple/code", {
      job_id: appleJobId,
      code: $("fp-auth-apple-code").value,
    });
    showApple2fa(false);
    await loadAuthStatus();
  } catch (err) {
    if (err.message !== "Locked") showAlert(err.message, "err");
  } finally {
    $("fp-auth-apple-code").value = "";
  }
}

/**
 * Wire the panel and read the current status (ruling R-P2-8).
 *
 * `root` is #fp-settings-signin. settings.js calls this again every time the
 * dialog opens; the listeners are wired once and only the status is re-read,
 * so a sign-in completed in another tab shows up on the next open.
 */
export function mountAuthPanel(root, { refresh = true } = {}) {
  if (!root) return;
  if (!mounted) {
    $("fp-auth-google-signin").addEventListener("click", startGoogleSignIn);
    $("fp-auth-apple-signin").addEventListener("click", submitAppleSignIn);
    $("fp-auth-apple-code-submit").addEventListener("click", submitAppleCode);
    mounted = true;
  }
  // Locked or unreachable: the lock screen is already up and there is nothing
  // to render, exactly as alerts.js treats its own first load.
  if (refresh) loadAuthStatus().catch(() => {});
}

/**
 * Wire the panel at page load, without reading status.
 *
 * The panel lives inside a closed dialog, so a GET /api/auth/status here buys
 * nothing and costs a request on the boot path, where it competes with the
 * device and day loads the dashboard is actually waiting for. settings.js
 * asks for the status when the dialog opens, which is the first moment anyone
 * can see it.
 */
export async function init() {
  await loadCatalog();
  mountAuthPanel($("fp-settings-signin"), { refresh: false });
}

init();
