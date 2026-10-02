/*
 * Unlock encrypted locations: open Find+'s own Chrome, wait for the screen lock.
 *
 * Purpose    : Drive POST /api/auth/google/unlock/start, GET
 *              /api/auth/google/unlock/progress and POST
 *              /api/auth/google/unlock/cancel. Shown only when the account is
 *              signed in but its E2EE key is still locked (`needs` includes
 *              `shared_key`). Google opens a Chrome window of Find+'s own; the
 *              person completes their Android phone's screen lock in it; Find+
 *              pastes nothing.
 * Inputs     : The Google card from google_card.js; deps from panel.js; a
 *              `settle` callback that re-reads status once the key is stored.
 * Outputs    : DOM state on the card's unlock block only.
 * Constraints: One poll at a time (JobPoller). A 401 stops quietly (the lock
 *              screen is already up). textContent only.
 */
"use strict";

import { t } from "../i18n.js";
import { JobPoller, describeError } from "./job_poller.js";

const PROGRESS_ROUTE = "/api/auth/google/unlock/progress";
const STATUS_ROUTE = "/api/auth/status";
const PROVIDER_ID = "google-find-hub";

function pollMs() {
  return window.__FP_TEST_STATUS_POLL_MS__ || 2000;
}
function pollCap() {
  return window.__FP_TEST_STATUS_POLL_CAP__ || 180;
}

export class GoogleUnlockFlow {
  constructor(card, deps, settle) {
    this.card = card;
    this.deps = deps;
    this.settle = settle;
    this.poller = new JobPoller(deps.api);
    this.jobId = null;
    this.cancelRequested = false;
    this.helperInstalled = false;
    this.timer = null;
    this.ticks = 0;
    this.nativeStart = null;
    card.unlockButton.addEventListener("click", () => this.start());
    card.unlockOwn.addEventListener("click", () => this.startOwnWindow());
    card.unlockCancel.addEventListener("click", () => this.cancel());
  }

  /** When the Find+ helper is detected, unlock through it; the separate Chrome
   *  window stays available as "other way". */
  setHelperInstalled(installed) {
    this.helperInstalled = !!installed;
    this.card.unlockOwn.hidden = !this.helperInstalled || !!this.nativeStart;
    let why = this.helperInstalled ? "signin.google.unlock.whyHelper" : "signin.google.unlock.why";
    if (this.nativeStart) why = "signin.native.unlockWhy";
    this.card.unlockWhy.textContent = t(why);
  }

  /** Show the block only for a signed-in account whose key is still locked. */
  render(provider) {
    const needs = (provider && provider.needs) || [];
    const show = !!(provider && provider.signed_in) && needs.includes("shared_key");
    this.card.unlock.hidden = !show;
    if (!show) {
      this.stopAll();
      this.reset();
    }
  }

  reset() {
    this.card.unlockStatus.hidden = true;
    this.card.unlockStatus.textContent = "";
    this.card.unlockError.hidden = true;
    this.card.unlockButton.disabled = false;
    this.card.unlockCancel.hidden = true;
  }

  busy(text) {
    this.card.unlockStatus.textContent = text;
    this.card.unlockStatus.hidden = false;
    this.card.unlockError.hidden = true;
    this.card.unlockButton.disabled = true;
    this.card.unlockCancel.hidden = false;
  }

  showError(message) {
    this.stopAll();
    this.card.unlockErrorDetail.textContent = message;
    this.card.unlockError.hidden = false;
    this.card.unlockStatus.hidden = true;
    this.card.unlockButton.disabled = false;
    this.card.unlockCancel.hidden = true;
  }

  stopAll() {
    this.poller.stop();
    this.stopTimer();
  }

  stopTimer() {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  /** The desktop app unlocks in the Find+ window (nativeStart, set by GoogleFlow). */
  start() {
    if (this.nativeStart) return this.nativeStart();
    return this.helperInstalled ? this.startHelper() : this.startOwnWindow();
  }

  /** The helper route: Google's unlock page opens in the user's own Chrome and
   *  the helper posts the key back; we just watch for the lock to clear. */
  async startHelper() {
    this.cancelRequested = false;
    this.busy(t("signin.google.unlock.helperOpening"));
    try {
      await this.deps.postJson("/api/auth/google/helper/unlock-begin");
    } catch (err) {
      if (err.status === 401) return this.reset();
      return this.showError(t("signin.error.startFailed", { message: describeError(err) }));
    }
    this.busy(t("signin.google.unlock.helperWaiting"));
    this.watchStatus();
  }

  watchStatus() {
    this.stopTimer();
    this.ticks = 0;
    const tick = async () => {
      if (++this.ticks > pollCap()) return this.showError(t("signin.google.unlock.helperTimeout"));
      try {
        const status = await this.deps.api(STATUS_ROUTE);
        const outcome = status.google_helper_outcome;
        if (outcome && outcome.ok === false && outcome.kind === "unlock") {
          return this.showError(outcome.message || t("signin.error.unknown"));
        }
        const google = (status.providers || []).find((p) => p.id === PROVIDER_ID);
        if (google && !(google.needs || []).includes("shared_key")) {
          this.stopTimer();
          await this.settle();
        }
      } catch (err) {
        if (err.status === 401) this.stopTimer();
      }
    };
    this.timer = setInterval(tick, pollMs());
    tick();
  }

  async startOwnWindow() {
    this.cancelRequested = false;
    this.busy(t("signin.google.unlock.starting"));
    try {
      const { job_id: jobId } = await this.deps.postJson("/api/auth/google/unlock/start");
      if (this.cancelRequested) return this.cancelJob(jobId);
      this.watch(jobId);
    } catch (err) {
      if (err.status === 401) return this.reset();
      const running = err.status === 409 && err.body ? err.body.job_id : null;
      if (running) return this.watch(running);
      this.showError(describeError(err));
    }
  }

  watch(jobId) {
    this.jobId = jobId;
    this.poller.start(PROGRESS_ROUTE, jobId, {
      onProgress: (progress) => this.onProgress(progress),
      onError: (message) => this.showError(message),
    });
  }

  onProgress(progress) {
    if (progress.state === "done") {
      this.poller.stop();
      return this.settle();
    }
    if (progress.state === "failed") {
      return this.showError(progress.message || t("signin.error.unknown"));
    }
    this.busy(progress.message || t("signin.google.unlock.waiting"));
  }

  async cancel() {
    this.cancelRequested = true;
    const jobId = this.jobId;
    this.stopAll();
    this.reset();
    if (jobId) await this.cancelJob(jobId);
  }

  async cancelJob(jobId) {
    try {
      await this.deps.postJson("/api/auth/google/unlock/cancel", { job_id: jobId });
    } catch (err) {
      // Best-effort: the job may already be done or swept.
    }
  }

  purge() {
    this.stopAll();
    this.reset();
    this.jobId = null;
    this.cancelRequested = false;
    this.card.unlock.hidden = true;
  }
}
