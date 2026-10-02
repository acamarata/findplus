/*
 * Apple Find My sign-in: one sheet, from Apple ID to "Connected as ...".
 *
 * Purpose    : Drive the Apple sheet (spec in-app-login §5, contract §5):
 *              POST /api/auth/apple/start, then GET /api/auth/apple/status for
 *              every phase (preparing, signing in, needs a code, success,
 *              error, cancelled), POST /api/auth/apple/code, "Use a text message
 *              instead" (POST /api/auth/apple/text) and Cancel (POST
 *              /api/auth/apple/cancel). The prompt names the trusted device or
 *              the masked number Apple reports. `needs: ["apple_extra"]` gets a
 *              plain explanation instead of a form that could only fail. DELETE
 *              /api/auth/apple-find-my disconnects, behind an inline confirm.
 * Inputs     : The Apple card from apple_card.js; deps from panel.js.
 * Outputs    : DOM state on that card; deps.onSettled() once signed in, then
 *              focus on the card's "Connected as ..." line.
 * Constraints: The password and the code leave their inputs the moment the
 *              request is sent, whatever the answer, and are never stored,
 *              echoed or re-read. Escape in the sheet cancels the sign-in and
 *              never reaches the Settings dialog behind it.
 */
"use strict";

import { t } from "../i18n.js";
import { FlowBase } from "./flow_base.js";
import { describeError } from "./job_poller.js";
import { wireDisconnect } from "./disconnect.js";
import { closeSheet, openSheet, wireSheetKeys } from "./sheet.js";

const STATUS_ROUTE = "/api/auth/apple/status";
const PROVIDER_ID = "apple-find-my";
const BUSY_KEYS = { preparing: "signin.apple.preparing", signing_in: "signin.apple.signingIn" };

export class AppleFlow extends FlowBase {
  constructor(card, deps, extra) {
    super(card, deps);
    this.extra = extra || null;
    this.jobId = null;
    this.wire();
  }

  wire() {
    const c = this.card;
    const on = (node, type, fn) => node.addEventListener(type, fn);
    const enter = (fn) => (e) => { if (e.key === "Enter") fn(); };
    for (const open of [c.connect, c.revokedButton, c.change]) on(open, "click", () => this.open());
    on(c.button, "click", () => this.start());
    on(c.password, "keydown", enter(() => this.start()));
    on(c.verify, "click", () => this.submitCode());
    on(c.code, "keydown", enter(() => this.submitCode()));
    on(c.textInstead, "click", () => this.textMe());
    on(c.retry, "click", () => this.restart(true));
    on(c.codeRestart, "click", () => this.restart(true));
    on(c.cancel, "click", () => this.cancel());
    wireSheetKeys(c.sheet, () => this.cancel());
    this.disconnectRow = wireDisconnect(this, PROVIDER_ID, (m) => { c.note.textContent = m; });
    on(c.appleId, "input", () => this.clearFieldErrors());
    on(c.password, "input", () => this.clearFieldErrors());
  }

  /** One GET /api/auth/status entry (or undefined: no Apple provider at all). */
  render(provider) {
    const unavailable = !provider || (provider.needs || []).includes("apple_extra");
    this.signedIn = !!(provider && provider.signed_in);
    const revoked = !!provider && provider.attention === "reauth";
    this.account = (provider && provider.account) || "";
    this.card.account.textContent = revoked ? t("signin.account.revoked")
      : this.signedIn ? t("signin.account.signedIn", { account: provider.account })
        : t("signin.account.signedOut");
    this.card.unavailable.hidden = !unavailable;
    this.card.how.hidden = unavailable;
    if (this.extra) this.extra.hidden = unavailable;
    if (unavailable) return this.showUnavailable();
    this.card.revoked.hidden = !revoked;
    this.card.ready.hidden = !this.signedIn || revoked;
    this.card.connect.hidden = this.signedIn || revoked;
    this.card.change.hidden = !this.signedIn || revoked;
    this.card.disconnect.hidden = !this.signedIn;
    if (revoked) this.card.root.dataset.attention = "reauth";
    else delete this.card.root.dataset.attention;
    if (!this.signedIn) this.hideDisconnectConfirm();
    if (!this.busy && !this.card.sheet.open && this.card.root.dataset.state !== "failed") {
      this.showIdle();
    }
  }

  showUnavailable() {
    this.poller.stop();
    closeSheet(this.card.sheet);
    this.card.root.dataset.state = "unavailable";
    const c = this.card;
    for (const part of [c.connect, c.change, c.disconnect, c.disconnectConfirm.row, c.ready,
      c.revoked]) part.hidden = true;
  }

  /** Open the sheet on a clean Apple ID step; a lost sign-in keeps the ID. */
  open() {
    this.backToForm();
    this.card.note.textContent = "";
    if (!this.card.appleId.value && this.account) this.card.appleId.value = this.account;
    openSheet(this.card.sheet);
    (this.card.appleId.value ? this.card.password : this.card.appleId).focus();
  }

  setFieldError(node, message) {
    node.textContent = message;
    node.hidden = false;
  }

  clearFieldErrors() {
    for (const node of [this.card.appleIdError, this.card.passwordError]) {
      node.textContent = "";
      node.hidden = true;
    }
  }

  /** The credentials step again, nothing typed kept but the Apple ID. */
  backToForm() {
    this.poller.stop();
    this.jobId = null;
    this.clearFieldErrors();
    this.card.code.value = "";
    this.card.codeRow.hidden = true;
    this.card.form.hidden = false;
    this.showIdle();
  }

  /** Start over (or Try again): drop the job, back to the Apple ID field. */
  restart(cancelJob) {
    if (cancelJob && this.jobId) this.postCancel(this.jobId);
    this.backToForm();
    this.card.appleId.focus();
  }

  async start() {
    const appleId = this.card.appleId.value.trim();
    const password = this.card.password.value;
    this.clearFieldErrors();
    if (!appleId) this.setFieldError(this.card.appleIdError, t("signin.apple.missingAppleId"));
    if (!password) this.setFieldError(this.card.passwordError, t("signin.apple.missingPassword"));
    if (!appleId || !password) return;
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
    this.poller.start(STATUS_ROUTE, jobId, {
      onProgress: (status) => this.onStatus(status),
      onError: (message) => this.showError(message),
    });
  }

  /** One GET /api/auth/apple/status answer (contract §5). */
  onStatus(status) {
    switch (status.phase) {
      case "needs_code": return this.askForCode(status.second_factor);
      case "success": return this.done();
      case "error": return this.showError(status.message || t("signin.error.unknown"));
      case "cancelled": return this.closeWith(t("signin.apple.cancelled"));
      default: {
        const key = BUSY_KEYS[status.phase];
        return key ? this.showBusy(t(key)) : undefined;
      }
    }
  }

  /** The code step, worded for a trusted device or for the number texted. */
  askForCode(factor) {
    this.poller.stop();
    this.showIdle();
    this.card.form.hidden = true;
    this.card.codeRow.hidden = false;
    this.promptFor(factor && factor.kind === "sms" ? factor.phone : null);
    this.card.textInstead.hidden = !(factor && factor.can_text && factor.kind !== "sms");
    this.card.code.focus();
  }

  promptFor(phone) {
    this.card.codePrompt.textContent = phone
      ? t("signin.apple.codeSms", { phone })
      : t("signin.apple.codeDevice");
  }

  /** "Use a text message instead": Apple texts the code to the first number. */
  async textMe() {
    this.card.textInstead.disabled = true;
    this.showBusy(t("signin.apple.texting"));
    try {
      const answer = await this.deps.postJson("/api/auth/apple/text", { job_id: this.jobId });
      this.showIdle();
      this.promptFor((answer && answer.phone) || t("signin.apple.yourPhone"));
      this.card.textInstead.hidden = true;
      this.card.code.focus();
    } catch (err) {
      this.showError(describeError(err));
    } finally {
      this.card.textInstead.disabled = false;
    }
  }

  async submitCode() {
    const code = this.card.code.value.replace(/\s+/g, "");
    if (!code) return this.showError(t("signin.apple.missingCode"));
    if (!/^\d{6}$/.test(code)) return this.showError(t("signin.apple.badFormat"));
    this.card.code.value = "";
    this.showBusy(t("signin.apple.checking"));
    this.card.verify.disabled = true;
    try {
      await this.deps.postJson("/api/auth/apple/code", { job_id: this.jobId, code });
      await this.done();
    } catch (err) {
      this.onRequestError(err, "code");
    } finally {
      this.card.verify.disabled = false;
    }
  }

  /** Signed in: close the sheet, repaint, focus "Connected as ...". */
  async done() {
    this.poller.stop();
    this.jobId = null;
    this.closeWith("");
    await this.settle();
    this.card.account.tabIndex = -1;
    this.card.account.focus();
  }

  closeWith(note) {
    this.poller.stop();
    closeSheet(this.card.sheet);
    this.backToForm();
    this.card.note.textContent = note;
  }

  /** Cancel (button or Escape): nothing is saved, focus back on Connect. */
  cancel() {
    if (!this.card.sheet.open && !this.jobId) return; // already closed (Escape + cancel event)
    const job = this.jobId;
    this.closeWith(job ? t("signin.apple.cancelled") : "");
    const back = [this.card.connect, this.card.change, this.card.revokedButton]
      .find((node) => !node.hidden && !node.closest("[hidden]"));
    if (back) back.focus();
    if (job) this.postCancel(job);
  }

  async postCancel(jobId) {
    try {
      await this.deps.postJson("/api/auth/apple/cancel", { job_id: jobId });
    } catch (_err) {
      // Best effort: the job may already be over.
    }
  }

  hideDisconnectConfirm() {
    this.disconnectRow.hide();
  }

  purge() {
    super.purge();
    closeSheet(this.card.sheet);
    this.jobId = null;
    this.account = "";
    this.clearFieldErrors();
    this.hideDisconnectConfirm();
    for (const input of [this.card.appleId, this.card.password, this.card.code]) input.value = "";
    this.card.codeRow.hidden = true;
    this.card.note.textContent = "";
  }
}
