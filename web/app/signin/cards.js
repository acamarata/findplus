/*
 * Sign-in provider cards: the DOM both sign-in surfaces share.
 *
 * Purpose    : Build the Google Find Hub and Apple Find My cards once, the
 *              same way for the setup wizard's sign-in step and for Settings >
 *              Sign-in, so the two can never look or behave differently again.
 * Inputs     : An id prefix ("fp-setup" in the wizard, "fp-auth" in Settings),
 *              the heading level that fits the surrounding page, and whether
 *              to print each provider's honesty sentence under its card.
 * Outputs    : { root, ...named elements } per card, for the flows in
 *              google_flow.js / apple_flow.js to drive.
 * Constraints: textContent only. Every string comes from t() or from the
 *              /api/config notices the caller passes in. The buttons name what
 *              happens ("Connect Google Find Hub"); they deliberately copy no
 *              vendor sign-in button, logo or wordmark: Find+ uses neither
 *              vendor's identity service and says it is not affiliated. The
 *              icons are neutral Lucide glyphs from the bundled sprite.
 */
"use strict";

import { t } from "../i18n.js";
import { loadIconSprite } from "../icon_sprite.js";

const SVG_NS = "http://www.w3.org/2000/svg";
export const CHROME_URL = "https://www.google.com/chrome/";

/** A plain element with an optional class, id and text. */
export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(className, label, id) {
  const btn = el("button", className, label);
  btn.type = "button";
  if (id) btn.id = id;
  return btn;
}

/** A decorative Lucide glyph: hidden from assistive tech, coloured by CSS. */
function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "fp-signin-icon-svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#lucide-${name}`);
  svg.append(use);
  return svg;
}

/** A labelled input stacked above its field, used by the Apple form. */
function field(labelText, id, type, autocomplete) {
  const label = el("label", "fp-signin-field");
  const input = el("input");
  input.type = type;
  input.id = id;
  input.autocomplete = autocomplete;
  label.append(el("span", "fp-signin-label", labelText), input);
  return { label, input };
}

/** Icon, provider name and the "Signed in as ..." line. */
function head(glyph, headingText, level, statusId) {
  const wrap = el("div", "fp-signin-head");
  const badge = el("span", "fp-signin-icon");
  badge.append(icon(glyph));
  const titles = el("div", "fp-signin-titles");
  const heading = el(`h${level}`, "fp-auth-provider", headingText);
  const account = el("p", "fp-signin-account");
  account.id = statusId;
  titles.append(heading, account);
  wrap.append(badge, titles);
  return { wrap, account };
}

/**
 * The in-progress line and the failure box every card carries.
 *
 * The line is a polite live region so "Opening Chrome..." and the steps after
 * it are announced; the failure box is role="alert" and always offers Retry,
 * so a failure is never silent and never a dead end.
 */
function feedback(prefix) {
  const progress = el("div", "fp-signin-progress");
  progress.id = `${prefix}-progress`;
  progress.setAttribute("role", "status");
  progress.setAttribute("aria-live", "polite");
  progress.hidden = true;
  const progressText = el("span", "fp-signin-progress-text");
  progress.append(el("span", "fp-signin-spinner"), progressText);

  const error = el("div", "fp-signin-error");
  error.id = `${prefix}-error`;
  error.setAttribute("role", "alert");
  error.hidden = true;
  const errorTitle = el("p", "fp-signin-error-title", t("signin.error.title"));
  const errorDetail = el("p", "fp-signin-error-detail");
  const retry = button("btn btn-secondary fp-signin-retry", t("signin.retry"), `${prefix}-retry`);
  error.append(errorTitle, errorDetail, retry);
  return { progress, progressText, error, errorDetail, retry };
}

function card(id, provider) {
  const root = el("section", "fp-signin-card");
  root.id = id;
  root.dataset.provider = provider;
  root.dataset.state = "idle";
  return root;
}

/** The Chrome-missing notice, its download link and a re-check button. */
function chromeBlock(prefix, notices) {
  const wrap = el("div", "fp-signin-chrome");
  wrap.hidden = true;
  const notice = el("p", "fp-signin-note", notices.chrome_required || "");
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

/** The Google Find Hub card: one button that opens Chrome, then feedback. */
export function buildGoogleCard({ prefix, level, notices, withNotices }) {
  loadIconSprite().catch(() => {});
  const root = card(`${prefix}-google-card`, "google");
  const top = head("compass", t("signin.google.heading"), level, `${prefix}-google-status`);
  const how = el("p", "fp-signin-how", t("signin.google.how"));
  const actions = el("div", "fp-signin-actions");
  const signin = button("btn fp-signin-btn", t("signin.google.connect"), `${prefix}-google-signin`);
  actions.append(signin);
  const fb = feedback(`${prefix}-google`);
  const chrome = chromeBlock(prefix, notices);
  root.append(top.wrap, how, actions, fb.progress, fb.error, chrome.chrome);
  if (withNotices) root.append(el("p", "fp-wizard-footnote", notices.find_hub || ""));
  return { root, account: top.account, button: signin, ...fb, ...chrome };
}

/** The 2FA row the Apple card reveals once the server asks for a code. */
function codeRow(prefix) {
  const row = el("div", "fp-signin-form");
  row.id = `${prefix}-apple-2fa`;
  row.hidden = true;
  const code = field(t("signin.apple.code"), `${prefix}-apple-code`, "text", "one-time-code");
  code.input.inputMode = "numeric";
  const verify = button("btn fp-signin-btn", t("signin.apple.verify"), `${prefix}-apple-code-submit`);
  const actions = el("div", "fp-signin-actions");
  actions.append(verify);
  row.append(el("p", "fp-signin-how", t("signin.apple.codePrompt")), code.label, actions);
  return { codeRow: row, code: code.input, verify };
}

/** The Apple Find My card: Apple ID + password, then the 2FA code. */
export function buildAppleCard({ prefix, level, notices, withNotices }) {
  loadIconSprite().catch(() => {});
  const root = card(`${prefix}-apple-card`, "apple");
  const top = head("key-round", t("signin.apple.heading"), level, `${prefix}-apple-status`);
  const how = el("p", "fp-signin-how", t("signin.apple.how"));
  const unavailable = el("p", "fp-signin-note", t("signin.apple.unavailable"));
  unavailable.id = `${prefix}-apple-unavailable`;
  unavailable.hidden = true;

  const form = el("div", "fp-signin-form");
  form.id = `${prefix}-apple-form`;
  const appleId = field(t("signin.apple.appleId"), `${prefix}-apple-id`, "text", "username");
  const password = field(t("signin.apple.password"), `${prefix}-apple-password`, "password", "current-password");
  const actions = el("div", "fp-signin-actions");
  const signin = button("btn fp-signin-btn", t("signin.apple.connect"), `${prefix}-apple-signin`);
  actions.append(signin);
  form.append(appleId.label, password.label, actions);

  const change = button("btn btn-secondary", t("signin.apple.switch"), `${prefix}-apple-switch`);
  change.hidden = true;
  const code = codeRow(prefix);
  const fb = feedback(`${prefix}-apple`);
  root.append(top.wrap, how, unavailable, form, change, code.codeRow, fb.progress, fb.error);
  if (withNotices) root.append(el("p", "fp-wizard-footnote", notices.apple || ""));
  return {
    root, account: top.account, how, unavailable, form, change,
    appleId: appleId.input, password: password.input, button: signin, ...code, ...fb,
  };
}
