/*
 * The primary Google path: one "Sign in with Google" button that uses the
 * Find+ helper extension in the user's own Chrome.
 *
 * Purpose    : POST /api/auth/google/helper/begin (the daemon opens a 127.0.0.1
 *              page in Chrome; the helper redirects to Google and posts the
 *              token back), then poll /api/auth/status until Google is signed
 *              in and let the card advance on its own. If the helper is not
 *              installed the sign-in never completes, so a gentle timeout points
 *              to the one-time install, written out as steps on the card.
 * Inputs     : the Google card from google_card.js; deps from panel.js; a
 *              `settle` callback (re-reads status and repaints).
 * Outputs    : DOM state on the card's hello block only.
 * Constraints: One status poll at a time. A 401 stops quietly (the lock screen
 *              is up). textContent only.
 */
"use strict";

import { t } from "../i18n.js";
import { describeError } from "./job_poller.js";
import { wireHelperSteps } from "./helper_steps.js";

const STATUS_ROUTE = "/api/auth/status";
const PROVIDER_ID = "google-find-hub";

function pollMs() {
  return window.__FP_TEST_STATUS_POLL_MS__ || 2000;
}
function pollCap() {
  return window.__FP_TEST_STATUS_POLL_CAP__ || 180;
}

export class GoogleHelperFlow {
  constructor(card, deps, settle) {
    this.card = card;
    this.deps = deps;
    this.settle = settle;
    this.timer = null;
    this.ticks = 0;
    this.baseline = null;
    card.hello.addEventListener("click", () => this.start());
    card.helloRetry.addEventListener("click", () => this.start());
    card.helloCancel.addEventListener("click", () => this.cancel());
    // The install steps are text only (helper_steps.js): nothing here opens
    // Finder or chrome://extensions; the folder path is looked up on open.
    wireHelperSteps(card, deps.postJson);
  }

  /** Reflect status.google_helper_installed on the card. */
  setHelperInstalled(installed) {
    this.card.helperInstalled.hidden = !installed;
  }

  reset() {
    this.stopPoll();
    this.card.helloStatusRow.hidden = true;
    this.card.helloStatus.textContent = "";
    this.card.helloError.hidden = true;
    this.card.helloCancel.hidden = true;
    this.card.hello.disabled = false;
  }

  busy(text) {
    this.card.helloStatus.textContent = text;
    this.card.helloStatusRow.hidden = false;
    this.card.helloError.hidden = true;
    this.card.helloCancel.hidden = false;
    this.card.hello.disabled = true;
  }

  showError(message) {
    this.stopPoll();
    this.card.helloErrorDetail.textContent = message;
    this.card.helloError.hidden = false;
    this.card.helloStatusRow.hidden = true;
    this.card.helloCancel.hidden = true;
    this.card.hello.disabled = false;
  }

  async start() {
    this.busy(t("signin.google.hello.opening"));
    try {
      const begun = await this.deps.postJson("/api/auth/google/helper/begin");
      // The sign-in generation at the moment Chrome opened. When already signed
      // in, only a LATER generation means the new sign-in landed.
      this.baseline = begun && typeof begun.generation === "number" ? begun.generation : null;
    } catch (err) {
      if (err.status === 401) return this.reset();
      return this.showError(t("signin.error.startFailed", { message: describeError(err) }));
    }
    this.busy(t("signin.google.hello.waiting"));
    this.watch();
  }

  watch() {
    this.stopPoll();
    this.ticks = 0;
    const tick = async () => {
      if (++this.ticks > pollCap()) return this.showError(t("signin.google.hello.timeout"));
      try {
        const status = await this.deps.api(STATUS_ROUTE);
        const outcome = status.google_helper_outcome;
        if (outcome && outcome.ok === false && outcome.kind === "signin") {
          // The helper handed the sign-in over and Find+ could not finish it.
          return this.showError(outcome.message || t("signin.error.unknown"));
        }
        const google = (status.providers || []).find((p) => p.id === PROVIDER_ID);
        if (google && google.signed_in && this.landed(status)) {
          this.reset();
          await this.settle();
        }
      } catch (err) {
        if (err.status === 401) this.stopPoll();
      }
    };
    this.timer = setInterval(tick, pollMs());
    tick();
  }

  /** True once the sign-in this click started has been stored. */
  landed(status) {
    if (this.baseline === null) return true;
    return (status.google_signin_generation || 0) > this.baseline;
  }

  stopPoll() {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  cancel() {
    this.reset();
  }

  render(provider) {
    // Only offer the primary button while signed out; once signed in the card
    // shows the account (and the unlock step) instead.
    const signedIn = !!(provider && provider.signed_in);
    this.card.hello.textContent = t(
      signedIn ? "signin.google.switch" : "signin.google.hello.button"
    );
    if (signedIn) this.reset();
  }

  purge() {
    this.reset();
  }
}
