/*
 * Google sign-in with your own Chrome: open Google's page, paste the token.
 *
 * Purpose    : Drive POST /api/auth/google/open (Google's EmbeddedSetup page
 *              in the Chrome people already use) and POST
 *              /api/auth/google/token (the `oauth_token` cookie they copy from
 *              it). Shows which browser got the page, the steps, and every
 *              failure in plain words inside the card.
 * Inputs     : The Google card from google_card.js; the panel's deps; a
 *              `settle` callback that re-reads sign-in status once done.
 * Outputs    : DOM state on the card's token panel only. The automatic flow's
 *              progress and error box (google_flow.js) are left alone.
 * Constraints: The token leaves its input the moment Connect sends it, whatever
 *              the answer, and is never stored, logged or re-read here (the
 *              Apple password field does the same). textContent only.
 */
"use strict";

import { t } from "../i18n.js";
import { describeError } from "./job_poller.js";

export class GoogleTokenFlow {
  constructor(card, deps, settle) {
    this.card = card;
    this.deps = deps;
    this.settle = settle;
    card.open.addEventListener("click", () => this.open());
    card.connect.addEventListener("click", () => this.connect());
    card.tokenInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") this.connect();
    });
    card.email.addEventListener("input", () => this.clearErrors());
    card.tokenInput.addEventListener("input", () => this.clearErrors());
  }

  /** Open Google's page in the user's Chrome, then show the steps either way. */
  async open() {
    const { open } = this.card;
    open.disabled = true;
    this.clearErrors();
    try {
      const { browser } = await this.deps.postJson("/api/auth/google/open");
      const key = browser === "chrome" ? "openedChrome" : "openedDefault";
      this.showPanel(t(`signin.google.token.${key}`));
    } catch (err) {
      if (err.status === 401) return;
      // The steps still work if the person opens the page themselves.
      this.showPanel("");
      this.showError(describeError(err));
    } finally {
      open.disabled = false;
    }
  }

  showPanel(openedText) {
    const { tokenPanel, opened, email } = this.card;
    tokenPanel.hidden = false;
    opened.textContent = openedText;
    opened.hidden = !openedText;
    email.focus();
  }

  fieldError(el, message) {
    el.textContent = message;
    el.hidden = false;
  }

  clearErrors() {
    for (const el of [this.card.emailError, this.card.tokenInputError]) {
      el.textContent = "";
      el.hidden = true;
    }
    this.card.tokenError.hidden = true;
    this.card.tokenErrorDetail.textContent = "";
  }

  showError(message) {
    this.card.tokenErrorDetail.textContent = message;
    this.card.tokenError.hidden = false;
  }

  setBusy(on) {
    this.card.connect.disabled = on;
    this.card.tokenStatus.hidden = !on;
    this.card.tokenStatus.textContent = on ? t("signin.google.token.checking") : "";
  }

  /** Send the email and token; the token field is emptied before the request. */
  async connect() {
    if (this.card.connect.disabled) return;
    const email = this.card.email.value.trim();
    const token = this.card.tokenInput.value.trim();
    this.clearErrors();
    if (!email) return this.fieldError(this.card.emailError, t("signin.google.token.missingEmail"));
    if (!token) {
      return this.fieldError(this.card.tokenInputError, t("signin.google.token.missingToken"));
    }
    this.card.tokenInput.value = "";
    this.setBusy(true);
    try {
      await this.deps.postJson("/api/auth/google/token", { email, oauth_token: token });
      this.hide();
      await this.settle();
    } catch (err) {
      if (err.status !== 401) this.showError(describeError(err));
    } finally {
      this.setBusy(false);
    }
  }

  /** Back to the closed panel (success, a lock, or a re-render). */
  hide() {
    this.clearErrors();
    this.setBusy(false);
    this.card.tokenInput.value = "";
    this.card.tokenPanel.hidden = true;
  }

  /** Lock purge: no typed email or token survives it. */
  purge() {
    this.hide();
    this.card.email.value = "";
    this.card.opened.textContent = "";
  }
}
