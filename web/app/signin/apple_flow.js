/*
 * Apple Find My sign-in: Apple ID and password, then the 2FA code.
 *
 * Purpose    : Drive POST /api/auth/apple/start, GET /api/auth/apple/progress
 *              and POST /api/auth/apple/code, showing every state they report
 *              (signing in, needs a code, checking it, done, failed) plus the
 *              one the status route reports up front: `needs: ["apple_extra"]`,
 *              a pip install without the Apple extra. That state gets a plain
 *              explanation instead of a form that could only fail.
 * Inputs     : The Apple card from cards.js; deps from panel.js.
 * Outputs    : DOM state on that card; deps.onSettled() once signed in.
 * Constraints: The password and the code leave their inputs the moment the
 *              request is sent, whatever the answer, and are never stored,
 *              echoed or re-read (settings.js's PIN fields do the same).
 */
"use strict";

import { t } from "../i18n.js";
import { FlowBase } from "./flow_base.js";
import { describeError } from "./job_poller.js";

const PROGRESS_ROUTE = "/api/auth/apple/progress";

export class AppleFlow extends FlowBase {
  constructor(card, deps, extra) {
    super(card, deps);
    this.extra = extra || null;
    this.jobId = null;
    card.button.addEventListener("click", () => this.start());
    card.verify.addEventListener("click", () => this.submitCode());
    card.retry.addEventListener("click", () => this.restart());
    card.change.addEventListener("click", () => this.restart());
  }

  /** One GET /api/auth/status entry (or undefined: no Apple provider at all). */
  render(provider) {
    const unavailable = !provider || (provider.needs || []).includes("apple_extra");
    this.signedIn = !!(provider && provider.signed_in);
    this.card.account.textContent = this.signedIn
      ? t("signin.account.signedIn", { account: provider.account })
      : t("signin.account.signedOut");
    this.card.unavailable.hidden = !unavailable;
    this.card.how.hidden = unavailable;
    if (this.extra) this.extra.hidden = unavailable;
    if (unavailable) return this.showUnavailable();
    if (this.busy || !this.card.codeRow.hidden) return;
    if (this.card.root.dataset.state !== "failed") this.showIdle();
    this.card.form.hidden = this.signedIn;
    this.card.change.hidden = !this.signedIn;
  }

  showUnavailable() {
    this.poller.stop();
    this.card.root.dataset.state = "unavailable";
    for (const part of [this.card.form, this.card.change, this.card.codeRow, this.card.progress, this.card.error]) {
      part.hidden = true;
    }
  }

  /** Back to the credentials form, empty, with the Apple ID field focused. */
  restart() {
    this.poller.stop();
    this.jobId = null;
    this.card.code.value = "";
    this.card.codeRow.hidden = true;
    this.card.change.hidden = true;
    this.card.form.hidden = false;
    this.showIdle();
    this.card.appleId.focus();
  }

  async start() {
    const appleId = this.card.appleId.value.trim();
    const password = this.card.password.value;
    if (!appleId || !password) return this.showError(t("signin.apple.missingFields"));
    this.card.password.value = "";
    this.showBusy(t("signin.apple.signingIn"));
    try {
      const { job_id: jobId } = await this.deps.postJson("/api/auth/apple/start", {
        apple_id: appleId,
        password,
      });
      this.watch(jobId);
    } catch (err) {
      this.onRequestError(err, "start");
    }
  }

  /** 409 rejoins, 503 means the extra is missing, anything else is shown. */
  onRequestError(err, phase) {
    const running = err.status === 409 && err.body ? err.body.job_id : null;
    if (running) return this.watch(running);
    if (err.status === 401) return this.showIdle();
    if (err.status === 503) return this.render({ needs: ["apple_extra"] });
    if (phase === "code" && err.status === 400) return this.showError(t("signin.error.badCode"));
    if (phase === "code" && err.status === 404) return this.showError(t("signin.error.expired"));
    const message = describeError(err);
    this.showError(phase === "start" ? t("signin.error.startFailed", { message }) : message);
  }

  watch(jobId) {
    this.jobId = jobId;
    this.poller.start(PROGRESS_ROUTE, jobId, {
      onProgress: (progress) => this.onProgress(progress),
      onError: (message) => this.showError(message),
    });
  }

  /** One poll's `{state, message}`. Exported for the tests. */
  onProgress(progress) {
    if (progress.state === "needs_2fa") return this.askForCode();
    if (progress.state === "done") return this.settle();
    if (progress.state === "failed") {
      return this.showError(progress.message || t("signin.error.unknown"));
    }
    this.showBusy(t("signin.apple.signingIn"));
  }

  askForCode() {
    this.poller.stop();
    this.showIdle();
    this.card.form.hidden = true;
    this.card.codeRow.hidden = false;
    this.card.code.focus();
  }

  async submitCode() {
    const code = this.card.code.value.trim();
    if (!code) return this.showError(t("signin.apple.missingCode"));
    this.card.code.value = "";
    this.showBusy(t("signin.apple.checking"));
    this.card.verify.disabled = true;
    try {
      await this.deps.postJson("/api/auth/apple/code", { job_id: this.jobId, code });
      this.card.codeRow.hidden = true;
      await this.settle();
    } catch (err) {
      this.onRequestError(err, "code");
    } finally {
      this.card.verify.disabled = false;
    }
  }

  purge() {
    super.purge();
    this.jobId = null;
    for (const input of [this.card.appleId, this.card.password, this.card.code]) input.value = "";
    this.card.codeRow.hidden = true;
  }
}
