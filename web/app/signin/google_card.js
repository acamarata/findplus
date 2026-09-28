/*
 * The Google Find Hub card: sign in with your own Chrome first, Find+'s own
 * Chrome window second.
 *
 * Purpose    : Build the Google card for both sign-in surfaces. The primary
 *              button opens Google's sign-in page in the Chrome people already
 *              use (POST /api/auth/google/open) and reveals the token panel:
 *              numbered steps to copy the `oauth_token` cookie, an email field,
 *              a token field and Connect (google_token_flow.js drives it). The
 *              smaller secondary button keeps the automatic flow, which opens a
 *              separate Chrome window (google_flow.js, unchanged behavior).
 * Inputs     : { prefix, level, notices, withNotices } like buildAppleCard.
 * Outputs    : { root, ...named elements }. `button` is the automatic flow's
 *              button, so FlowBase's busy/idle handling applies to it.
 * Constraints: textContent only, every string from t() or /api/config. Why
 *              the paste step exists: Chrome 136+ refuses automation of the
 *              default profile, and Google issues the Find Hub token only as
 *              that cookie. The token field is a password input with
 *              autocomplete off, cleared the moment Connect sends it.
 */
"use strict";

import { t } from "../i18n.js";
import { loadIconSprite } from "../icon_sprite.js";
import {
  CHROME_URL, button, card, chromeNoticeText, disconnectConfirmRow, el, feedback, field, head,
} from "./cards.js";

const STEP_KEYS = ["step1", "step2", "step3", "step4", "step5"];

/** The Chrome-missing notice, its download link and a re-check button. */
function chromeBlock(prefix, notices) {
  const wrap = el("div", "fp-signin-chrome");
  wrap.hidden = true;
  const notice = el("p", "fp-signin-note", chromeNoticeText(notices.chrome_required) || "");
  notice.id = `${prefix}-chrome-notice`;
  notice.hidden = true;
  const link = el("a", "fp-signin-link", t("signin.google.downloadChrome"));
  link.id = `${prefix}-chrome-download`;
  link.href = CHROME_URL;
  link.target = "_blank";
  link.rel = "noopener";
  link.hidden = true;
  const recheck = button("btn btn-secondary", t("signin.google.checkAgain"));
  wrap.append(notice, link, recheck);
  return { chrome: wrap, chromeNotice: notice, chromeLink: link, recheck };
}

/** The numbered "copy the oauth_token cookie" steps. */
function steps(prefix) {
  const list = el("ol", "fp-signin-steps");
  list.id = `${prefix}-google-steps`;
  for (const key of STEP_KEYS) list.append(el("li", "", t(`signin.google.token.${key}`)));
  return list;
}

/** A failure from /open or /token, in words. No Retry: Connect is right there. */
function tokenError(prefix) {
  const box = el("div", "fp-signin-error");
  box.id = `${prefix}-google-connect-error`;
  box.setAttribute("role", "alert");
  box.hidden = true;
  const detail = el("p", "fp-signin-error-detail");
  box.append(detail);
  return { tokenError: box, tokenErrorDetail: detail };
}

/** Steps, email, token and Connect, hidden until the page has been opened. */
function tokenPanel(prefix) {
  const panel = el("div", "fp-signin-form fp-signin-token");
  panel.id = `${prefix}-google-token-panel`;
  panel.hidden = true;
  const opened = el("p", "fp-signin-opened");
  opened.id = `${prefix}-google-opened`;
  opened.setAttribute("role", "status");
  const why = el("p", "fp-signin-how", t("signin.google.token.why"));
  const email = field(t("signin.google.token.email"), `${prefix}-google-email`, "email", "username",
    { withError: true });
  const token = field(t("signin.google.token.value"), `${prefix}-google-token`, "password", "off",
    { withError: true });
  token.input.spellcheck = false;
  const status = el("p", "fp-signin-how");
  status.id = `${prefix}-google-token-status`;
  status.setAttribute("role", "status");
  status.hidden = true;
  const connect = button("btn fp-signin-btn", t("signin.google.token.connect"), `${prefix}-google-connect`);
  const actions = el("div", "fp-signin-actions");
  actions.append(connect);
  const err = tokenError(prefix);
  panel.append(opened, why, steps(prefix), email.label, email.error, token.label, token.error,
    actions, status, err.tokenError);
  return {
    tokenPanel: panel, opened, email: email.input, emailError: email.error,
    tokenInput: token.input, tokenInputError: token.error, connect, tokenStatus: status, ...err,
  };
}

/**
 * The "Unlock encrypted locations" step, shown when the account is signed in
 * but its E2EE key is still locked (`needs` includes `shared_key`). Honest:
 * Google encrypts Find Hub locations end to end; unlocking needs the Android
 * phone's screen lock once, in a Chrome window Find+ opens itself, and Find+
 * never asks you to paste code. google_unlock_flow.js drives it.
 */
function unlockBlock(prefix) {
  const wrap = el("div", "fp-signin-unlock");
  wrap.id = `${prefix}-google-unlock`;
  wrap.hidden = true;
  const why = el("p", "fp-signin-how", t("signin.google.unlock.why"));
  const actions = el("div", "fp-signin-actions");
  const btn = button("btn fp-signin-btn", t("signin.google.unlock.button"), `${prefix}-google-unlock-btn`);
  const cancel = button("btn btn-secondary", t("signin.cancel"), `${prefix}-google-unlock-cancel`);
  cancel.hidden = true;
  actions.append(btn, cancel);
  const status = el("p", "fp-signin-how");
  status.id = `${prefix}-google-unlock-status`;
  status.setAttribute("role", "status");
  status.hidden = true;
  const error = el("div", "fp-signin-error");
  error.id = `${prefix}-google-unlock-error`;
  error.setAttribute("role", "alert");
  error.hidden = true;
  const errorDetail = el("p", "fp-signin-error-detail");
  error.append(errorDetail);
  wrap.append(el("p", "fp-signin-unlock-head", t("signin.google.unlock.heading")), why, actions,
    status, error);
  return {
    unlock: wrap, unlockButton: btn, unlockCancel: cancel, unlockStatus: status,
    unlockError: error, unlockErrorDetail: errorDetail,
  };
}

/**
 * The primary "Sign in with Google" button (google_helper_flow.js) and its own
 * status/cancel/error line. A neutral white button: no Google "G" artwork,
 * which is reserved for Google Identity Services. It signs in through the Find+
 * helper extension in the user's own Chrome.
 */
function helloBlock(prefix) {
  const wrap = el("div", "fp-signin-hello");
  const actions = el("div", "fp-signin-actions");
  const hello = button("btn fp-signin-btn fp-google-btn", t("signin.google.hello.button"),
    `${prefix}-google-hello`);
  actions.append(hello);
  const status = el("div", "fp-signin-progress");
  status.id = `${prefix}-google-hello-status`;
  status.setAttribute("role", "status");
  status.hidden = true;
  const statusText = el("span", "fp-signin-progress-text");
  const cancel = button("btn btn-secondary", t("signin.cancel"), `${prefix}-google-hello-cancel`);
  cancel.hidden = true;
  status.append(el("span", "fp-signin-spinner"), statusText, cancel);
  const error = el("div", "fp-signin-error");
  error.id = `${prefix}-google-hello-error`;
  error.setAttribute("role", "alert");
  error.hidden = true;
  const errorDetail = el("p", "fp-signin-error-detail");
  const retry = button("btn btn-secondary", t("signin.retry"), `${prefix}-google-hello-retry`);
  error.append(errorDetail, retry);
  wrap.append(actions, status, error);
  return {
    helloBlock: wrap, hello, helloStatus: statusText, helloStatusRow: status,
    helloCancel: cancel, helloError: error, helloErrorDetail: errorDetail, helloRetry: retry,
  };
}

/** The Google Find Hub card. Primary: "Sign in with Google" (the helper). The
 * paste flow and the separate-window flow move under an "Other ways" details. */
export function buildGoogleCard({ prefix, level, notices, withNotices }) {
  loadIconSprite().catch(() => {});
  const root = card(`${prefix}-google-card`, "google");
  const top = head("compass", t("signin.google.heading"), level, `${prefix}-google-status`);
  const how = el("p", "fp-signin-how", t("signin.google.how"));
  const hello = helloBlock(prefix);
  const disconnect = button("btn btn-secondary", t("signin.disconnect"), `${prefix}-google-disconnect`);
  disconnect.hidden = true;
  const disconnectRow = el("div", "fp-signin-actions");
  disconnectRow.append(disconnect);
  const disconnectConfirm = disconnectConfirmRow(prefix, "google", t("signin.google.disconnectConfirm"));
  const unlock = unlockBlock(prefix);

  // "Other ways to sign in": the paste flow and the separate-window flow, in a
  // native <details> so it collapses with no inline handler (CSP-safe).
  const other = document.createElement("details");
  other.className = "fp-signin-other";
  const summary = document.createElement("summary");
  summary.textContent = t("signin.google.otherWays");
  const open = button("btn fp-signin-btn", t("signin.google.openChrome"), `${prefix}-google-open`);
  const openRow = el("div", "fp-signin-actions");
  openRow.append(open);
  const panel = tokenPanel(prefix);
  const alt = el("div", "fp-signin-alt");
  const signin = button("btn btn-secondary fp-signin-alt-btn", t("signin.google.ownWindow"),
    `${prefix}-google-signin`);
  alt.append(signin);
  const fb = feedback(`${prefix}-google`, { withCancel: true });
  const chrome = chromeBlock(prefix, notices);
  other.append(summary, openRow, panel.tokenPanel, alt, fb.progress, fb.error, chrome.chrome);

  root.append(top.wrap, how, hello.helloBlock, disconnectRow, disconnectConfirm.row,
    unlock.unlock, other);
  if (withNotices) root.append(el("p", "fp-wizard-footnote", notices.find_hub || ""));
  return {
    root, account: top.account, open, button: signin, disconnect, disconnectConfirm, other,
    ...hello, ...unlock, ...panel, ...fb, ...chrome,
  };
}
