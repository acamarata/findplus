/*
 * Google Find Hub sign-in: open Chrome, wait for the person, save the session.
 *
 * Purpose    : Drive POST /api/auth/google/start and GET
 *              /api/auth/google/progress, and show every state they can
 *              report: starting ("Opening Chrome..."), waiting for the person
 *              in Chrome, capturing, done, failed, Chrome missing, a refused
 *              start, a lost daemon and a timeout. Nothing ends silently.
 * Inputs     : The Google card from cards.js; deps from panel.js.
 * Outputs    : DOM state on that card; deps.onSettled() once a job is done.
 * Constraints: The Chrome-missing sentence is honesty.CHROME_REQUIRED from
 *              /api/config (deps.notices()), never the thrown 400 text: the
 *              route's only 400 is ChromeNotFoundError, but the UI does not
 *              rely on that coincidence (T0 addendum B5). A 409 means a job is
 *              already running, so the flow rejoins it rather than opening a
 *              second Chrome (CR-C-E10 F1). The notice drops the sentence's
 *              own "Install it from <url>" clause (chromeNoticeText, UAT6
 *              N23): the Download Chrome link right beside it already is
 *              that action, so the raw URL is not also printed as text.
 *              Cancel (UAT6 N23) posts /api/auth/google/cancel; DELETE
 *              /api/auth/google-find-hub (S11/WP8) disconnects, behind an
 *              inline confirm row -- never window.confirm.
 */
"use strict";

import { t } from "../i18n.js";
import { googleChromeNoticeNeeded } from "../provider_chrome.js";
import { chromeNoticeText } from "./cards.js";
import { FlowBase } from "./flow_base.js";
import { describeError } from "./job_poller.js";

const PROGRESS_ROUTE = "/api/auth/google/progress";
const PROVIDER_ID = "google-find-hub";

/** Job state -> the catalog line that describes it while it runs. */
const BUSY_KEYS = {
  launching: "signin.google.starting",
  waiting_for_user: "signin.google.waiting",
  capturing: "signin.google.capturing",
};

export class GoogleFlow extends FlowBase {
  constructor(card, deps) {
    super(card, deps);
    this.jobId = null;
    this.cancelRequested = false;
    card.button.addEventListener("click", () => this.start());
    card.retry.addEventListener("click", () => this.start());
    card.recheck.addEventListener("click", () => this.deps.onSettled());
    card.cancel.addEventListener("click", () => this.cancel());
    card.disconnect.addEventListener("click", () => this.showDisconnectConfirm());
    card.disconnectConfirm.cancel.addEventListener("click", () => this.hideDisconnectConfirm());
    card.disconnectConfirm.confirm.addEventListener("click", () => this.confirmDisconnect());
  }

  /** One GET /api/auth/status entry (or undefined) onto the card. */
  render(provider) {
    this.signedIn = !!(provider && provider.signed_in);
    this.card.account.textContent = this.signedIn
      ? t("signin.account.signedIn", { account: provider.account })
      : t("signin.account.signedOut");
    this.card.button.textContent = t(this.signedIn ? "signin.google.switch" : "signin.google.connect");
    this.card.disconnect.hidden = !this.signedIn;
    if (!this.signedIn) this.hideDisconnectConfirm();
    if (this.busy) return;
    if (this.card.root.dataset.state !== "failed") this.showIdle();
    this.showChromeMissing(googleChromeNoticeNeeded(provider));
  }

  /** Chrome is not installed: the honesty sentence, a link, and no dead button. */
  showChromeMissing(on) {
    const { chrome, chromeNotice, chromeLink, button } = this.card;
    // /api/config first; the catalog's honesty block (generated verbatim from
    // honesty.py) if config has not loaded yet, so it is never blank. Either
    // way, chromeNoticeText() drops the sentence's own download-URL clause:
    // the link right below already is that action (UAT6 N23).
    const raw = this.deps.notices().chrome_required || t("honesty.chromeRequired");
    chromeNotice.textContent = chromeNoticeText(raw);
    chrome.hidden = !on;
    chromeNotice.hidden = !on;
    chromeLink.hidden = !on;
    button.disabled = on || this.busy;
    if (on) this.card.root.dataset.state = "blocked";
  }

  async start() {
    this.showChromeMissing(false);
    this.jobId = null;
    this.cancelRequested = false;
    this.card.disconnect.hidden = true;
    this.showBusy(t("signin.google.starting"));
    try {
      const { job_id: jobId } = await this.deps.postJson("/api/auth/google/start");
      if (this.cancelRequested) return this.cancelJob(jobId);
      this.watch(jobId);
    } catch (err) {
      this.onStartError(err);
    }
  }

  onStartError(err) {
    const running = err.status === 409 && err.body ? err.body.job_id : null;
    if (running) return this.watch(running);
    if (err.status === 401) return this.showIdle();
    if (err.status === 400) {
      this.showIdle();
      return this.showChromeMissing(true);
    }
    this.showError(t("signin.error.startFailed", { message: describeError(err) }));
  }

  /** Follow one job; `watch` also rejoins a job another click started. */
  watch(jobId) {
    this.jobId = jobId;
    this.poller.start(PROGRESS_ROUTE, jobId, {
      onProgress: (progress) => this.onProgress(progress),
      onError: (message) => this.showError(message),
    });
  }

  /** One poll's `{state, message, chrome_found}`. Exported for the tests. */
  onProgress(progress) {
    if (progress.chrome_found === false) {
      this.poller.stop();
      this.showIdle();
      return this.showChromeMissing(true);
    }
    if (progress.state === "done") return this.settle();
    if (progress.state === "failed") {
      return this.showError(progress.message || t("signin.error.unknown"));
    }
    const key = BUSY_KEYS[progress.state];
    if (key) this.showBusy(t(key));
  }

  /**
   * UAT6 N23: Cancel while waiting on Chrome. Stops the local poll right
   * away; a job not yet known (the /start request is still in flight) is
   * cancelled the moment it answers, via `cancelRequested`.
   */
  async cancel() {
    this.cancelRequested = true;
    const jobId = this.jobId;
    this.poller.stop();
    this.showIdle();
    if (jobId) await this.cancelJob(jobId);
  }

  async cancelJob(jobId) {
    try {
      await this.deps.postJson("/api/auth/google/cancel", { job_id: jobId });
    } catch (err) {
      // Best-effort: the job may already be done or swept. Nothing to show.
    }
  }

  /** S11/WP8: an inline "Disconnect Google Find Hub?" row, never window.confirm. */
  showDisconnectConfirm() {
    this.card.disconnectConfirm.row.hidden = false;
    this.card.disconnect.hidden = true;
    this.card.disconnectConfirm.confirm.focus();
  }

  hideDisconnectConfirm() {
    this.card.disconnectConfirm.row.hidden = true;
    this.card.disconnect.hidden = !this.signedIn;
  }

  async confirmDisconnect() {
    const { confirm } = this.card.disconnectConfirm;
    confirm.disabled = true;
    try {
      await this.deps.api(`/api/auth/${PROVIDER_ID}`, { method: "DELETE" });
      this.hideDisconnectConfirm();
      await this.settle();
    } catch (err) {
      this.hideDisconnectConfirm();
      this.showError(describeError(err));
    } finally {
      confirm.disabled = false;
    }
  }

  purge() {
    super.purge();
    this.jobId = null;
    this.cancelRequested = false;
    this.hideDisconnectConfirm();
    this.showChromeMissing(false);
  }
}
