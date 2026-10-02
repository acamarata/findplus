/*
 * The Google card's in-app block: one Connect button and the window's states.
 *
 * Purpose    : The DOM for the desktop app's Google sign-in (spec in-app-login
 *              §7): a status line that is the card's one polite live region, a
 *              note under it, and the few buttons each state offers (Connect,
 *              Show window, Cancel, Use your Chrome, Try again, ...). Which of
 *              them shows is decided by google_native_view.js.
 * Inputs     : The card's id prefix and the /api/config notices.
 * Outputs    : { native, nativeStatus, nativeText, nativeNote, ...buttons }.
 * Constraints: textContent only; every string from t() or /api/config. No
 *              "cookie" or "token" anywhere on this path. Built only when the
 *              page has the desktop bridge (native_bridge.js).
 */
"use strict";

import { t } from "../i18n.js";
import { button, el } from "./cards.js";

/** One button of the block, hidden until a state asks for it. */
function action(prefix, key, label, primary = false) {
  const cls = `${primary ? "btn fp-signin-btn" : "btn btn-secondary"} fp-signin-native-${key}`;
  const btn = button(cls, label, `${prefix}-google-native-${key}`);
  btn.hidden = true;
  return btn;
}

/** A quiet text-style button (Prefer your Chrome?, Try the window again). */
function quiet(prefix, key, label) {
  const btn = button("fp-signin-quiet", label, `${prefix}-google-native-${key}`);
  btn.hidden = true;
  return btn;
}

/** The status line: a spinner and one sentence, announced politely. */
function statusLine(prefix) {
  const row = el("div", "fp-signin-progress fp-signin-native-status");
  row.id = `${prefix}-google-native-status`;
  row.setAttribute("role", "status");
  row.setAttribute("aria-live", "polite");
  const spinner = el("span", "fp-signin-spinner");
  spinner.setAttribute("aria-hidden", "true");
  const text = el("span", "fp-signin-progress-text");
  text.id = `${prefix}-google-native-text`;
  row.append(spinner, text);
  return { nativeStatus: row, nativeSpinner: spinner, nativeText: text };
}

/** The in-app block of the Google card. */
export function buildNativeBlock(prefix, notices) {
  const wrap = el("div", "fp-signin-native");
  wrap.id = `${prefix}-google-native`;
  const status = statusLine(prefix);
  const note = el("p", "fp-signin-how fp-signin-native-note");
  note.id = `${prefix}-google-native-note`;
  note.hidden = true;
  const buttons = {
    nativeConnect: action(prefix, "connect", t("signin.connect"), true),
    nativeChrome: action(prefix, "chrome", t("signin.native.useChrome"), true),
    nativePaste: action(prefix, "paste", t("signin.native.showSteps"), true),
    nativeRetry: action(prefix, "retry", t("signin.retry"), true),
    nativeShow: action(prefix, "show", t("signin.native.showWindow")),
    nativeCancel: action(prefix, "cancel", t("signin.cancel")),
  };
  const quietButtons = {
    nativePrefer: quiet(prefix, "prefer", t("signin.native.preferChrome")),
    nativeWindowAgain: quiet(prefix, "window-again", t("signin.native.tryWindow")),
  };
  const actions = el("div", "fp-signin-actions");
  actions.append(...Object.values(buttons), ...Object.values(quietButtons));
  const honesty = el(
    "p", "fp-signin-how fp-signin-native-honesty",
    (notices && notices.native_signin) || t("honesty.nativeSignin")
  );
  honesty.id = `${prefix}-google-native-honesty`;
  wrap.append(status.nativeStatus, note, actions, honesty);
  return { native: wrap, nativeNote: note, nativeHonesty: honesty, ...status, ...buttons,
    ...quietButtons };
}
