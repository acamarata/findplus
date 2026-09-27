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

export class GoogleUnlockFlow {
  constructor(card, deps, settle) {
    this.card = card;
    this.deps = deps;
    this.settle = settle;
    this.poller = new JobPoller(deps.api);
    this.jobId = null;
    this.cancelRequested = false;
    card.unlockButton.addEventListener("click", () => this.start());
    card.unlockCancel.addEventListener("click", () => this.cancel());
  }

  /** Show the block only for a signed-in account whose key is still locked. */
  render(provider) {
    const needs = (provider && provider.needs) || [];
    const show = !!(provider && provider.signed_in) && needs.includes("shared_key");
    this.card.unlock.hidden = !show;
    if (!show) {
      this.poller.stop();
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
    this.poller.stop();
    this.card.unlockErrorDetail.textContent = message;
    this.card.unlockError.hidden = false;
    this.card.unlockStatus.hidden = true;
    this.card.unlockButton.disabled = false;
    this.card.unlockCancel.hidden = true;
  }

  async start() {
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
    this.poller.stop();
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
    this.poller.stop();
    this.reset();
    this.jobId = null;
    this.cancelRequested = false;
    this.card.unlock.hidden = true;
  }
}
