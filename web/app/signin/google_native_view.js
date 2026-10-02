/*
 * What the Google card's in-app block shows in each state.
 *
 * Purpose    : The spec's state table (in-app-login §7) as data: for each
 *              phase, the sentence, whether the spinner turns, which note sits
 *              under it and which buttons are offered. google_native_flow.js
 *              decides the phase; this file only paints it.
 * Inputs     : The card from google_card.js and a view
 *              { phase, message?, note?, fallback? }.
 * Outputs    : DOM on the in-app block; `data-phase` on the card root, which
 *              signin-native.css and the tests read.
 * Constraints: The status line is the card's one polite live region, so its
 *              text is written only when it changes: every state change is
 *              announced once. textContent only.
 */
"use strict";

import { t } from "../i18n.js";

const BUTTONS = [
  "nativeConnect", "nativeChrome", "nativePaste", "nativeRetry", "nativeShow",
  "nativeCancel", "nativePrefer", "nativeWindowAgain",
];

/** phase -> { key (default sentence), busy, tone, note, buttons }. */
const PHASES = {
  idle: { key: "", buttons: ["nativeConnect"] },
  helper_first: {
    key: "", note: "signin.native.startWithHelper",
    buttons: ["nativeChrome", "nativeWindowAgain"],
  },
  connecting: { key: "signin.native.connecting", busy: true, buttons: ["nativeCancel"] },
  waiting: {
    key: "signin.native.waiting", busy: true, note: "signin.native.titleNote",
    buttons: ["nativeShow", "nativeCancel", "nativePrefer"],
  },
  finishing: { key: "signin.native.finishing", busy: true, buttons: [] },
  needs_unlock: {
    key: "signin.native.needsUnlock", busy: true, note: "signin.native.titleNote",
    buttons: ["nativeShow", "nativeCancel"],
  },
  success: { key: "", buttons: [] },
  blocked_embedded: { key: "signin.native.blocked", tone: "error", buttons: ["nativeWindowAgain"] },
  error: { key: "signin.native.error", tone: "error", buttons: ["nativeRetry", "nativeChrome"] },
};

/** The fallback ladder's next step (contract §3.6): helper first, then paste. */
function blockedButtons(fallback) {
  const next = fallback === "use_paste" ? "nativePaste" : "nativeChrome";
  return [next, "nativeWindowAgain"];
}

/** Write the live sentence only when it changed, so it is announced once. */
function say(card, text) {
  if (card.nativeText.textContent !== text) card.nativeText.textContent = text;
}

/**
 * Paint one view. `message` (the daemon's words) wins over the default
 * sentence; an empty sentence hides the line. Returns the phase painted.
 */
export function paintNative(card, view) {
  const spec = PHASES[view.phase] || PHASES.idle;
  const text = view.message !== undefined ? view.message : spec.key ? t(spec.key) : "";
  card.root.dataset.phase = view.phase;
  card.nativeStatus.dataset.tone = spec.tone || "";
  card.nativeSpinner.hidden = !spec.busy;
  say(card, text);
  card.nativeStatus.hidden = !text;
  const noteKey = view.note || spec.note;
  card.nativeNote.textContent = noteKey ? t(noteKey) : "";
  card.nativeNote.hidden = !noteKey;
  const shown = view.phase === "blocked_embedded" ? blockedButtons(view.fallback) : spec.buttons;
  for (const name of BUTTONS) card[name].hidden = !shown.includes(name);
  return view.phase;
}

/** True for the phases in which the window may still be open. */
export function isLive(phase) {
  return ["connecting", "waiting", "finishing", "needs_unlock"].includes(phase);
}
