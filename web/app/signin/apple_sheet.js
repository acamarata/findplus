/*
 * The Apple sign-in sheet: Apple ID and password, then the 6-digit code.
 *
 * Purpose    : The DOM of the one sheet Apple sign-in happens in (spec
 *              in-app-login §5): a native <dialog> shown with showModal(), so
 *              focus stays inside and Escape cancels. Step one asks for the
 *              Apple ID and password; step two for the code from a trusted
 *              device, with "Use a text message instead" and Start over.
 *              apple_flow.js drives it.
 * Inputs     : The card's id prefix.
 * Outputs    : { sheet, sheetTitle, form, appleId, password, button, cancel,
 *              codeRow, codePrompt, code, verify, textInstead, codeRestart,
 *              ...feedback }.
 * Constraints: The sheet lives inside the Apple card, so the wizard's draft
 *              keeper never keeps the password (wizard_drafts.js). The
 *              password field is cleared the moment a sign-in is sent.
 *              textContent only; every string through t().
 */
"use strict";

import { t } from "../i18n.js";
import { button, el, feedback, field } from "./cards.js";

/** Apple ID, password, and the one Sign in button. */
function credentials(prefix) {
  const form = el("div", "fp-signin-form");
  form.id = `${prefix}-apple-form`;
  const appleId = field(t("signin.apple.appleId"), `${prefix}-apple-id`, "text", "username",
    { withError: true });
  const password = field(t("signin.apple.password"), `${prefix}-apple-password`, "password",
    "current-password", { withError: true });
  const note = el("p", "fp-signin-how", t("signin.apple.passwordNote"));
  const actions = el("div", "fp-signin-actions");
  const signin = button("btn fp-signin-btn", t("signin.apple.signIn"), `${prefix}-apple-sheet-submit`);
  actions.append(signin);
  form.append(appleId.label, appleId.error, password.label, password.error, note, actions);
  return {
    form, button: signin, appleId: appleId.input, appleIdError: appleId.error,
    password: password.input, passwordError: password.error,
  };
}

/** The code step: prompt, field, Verify, text instead, Start over. */
function codeStep(prefix) {
  const row = el("div", "fp-signin-form");
  row.id = `${prefix}-apple-2fa`;
  row.hidden = true;
  const prompt = el("p", "fp-signin-how fp-signin-code-prompt", t("signin.apple.codePrompt"));
  prompt.id = `${prefix}-apple-code-prompt`;
  const code = field(t("signin.apple.code"), `${prefix}-apple-code`, "text", "one-time-code");
  code.input.inputMode = "numeric";
  code.input.maxLength = 12; // room for "123 456"; the flow strips spaces and wants 6 digits
  code.input.classList.add("fp-signin-code");
  code.input.setAttribute("aria-describedby", prompt.id);
  const verify = button("btn fp-signin-btn", t("signin.apple.verify"), `${prefix}-apple-code-submit`);
  const text = button("btn btn-secondary", t("signin.apple.textInstead"), `${prefix}-apple-text`);
  text.hidden = true;
  const startOver = button("btn btn-secondary", t("signin.apple.startOver"),
    `${prefix}-apple-code-restart`);
  const actions = el("div", "fp-signin-code-actions");
  actions.append(verify, text, startOver);
  row.append(prompt, code.label, actions);
  return { codeRow: row, codePrompt: prompt, code: code.input, verify, textInstead: text,
    codeRestart: startOver };
}

/** The sheet itself. */
export function buildAppleSheet(prefix) {
  const sheet = document.createElement("dialog");
  sheet.className = "fp-signin-sheet";
  sheet.id = `${prefix}-apple-sheet`;
  const title = el("h2", "fp-signin-sheet-title", t("signin.apple.sheetTitle"));
  title.id = `${prefix}-apple-sheet-title`;
  sheet.setAttribute("aria-labelledby", title.id);
  const creds = credentials(prefix);
  const code = codeStep(prefix);
  const fb = feedback(`${prefix}-apple`);
  const foot = el("div", "fp-signin-sheet-foot");
  const cancel = button("btn btn-secondary", t("signin.cancel"), `${prefix}-apple-sheet-cancel`);
  foot.append(cancel);
  sheet.append(title, creds.form, code.codeRow, fb.progress, fb.error, foot);
  return { sheet, sheetTitle: title, ...creds, ...code, ...fb, cancel };
}
