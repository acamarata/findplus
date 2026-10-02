/*
 * Which in-app sign-in a piece of news belongs to (the daemon's flow id).
 *
 * Purpose    : The daemon's progress is the one truth (contract §3.8). Every
 *              begin answer, progress answer and shell event carries `flow`.
 *              A card that started flow X ignores news from any other flow, so
 *              an older window's late success never finishes a newer sign-in
 *              (r12 #4). A card that follows a window it did not start (tray,
 *              deep link, or a window already open) takes the flow it sees.
 * Inputs     : The card's flow (or null) and a payload's `flow`.
 * Outputs    : sameFlow(); isWindowOpen(); beginBody().
 * Constraints: Pure functions, no DOM, no network.
 */
"use strict";

/** True when news with `theirs` may move a card following `mine`. */
export function sameFlow(mine, theirs) {
  return !mine || !theirs || mine === theirs;
}

/** True for the daemon's "a window is still working" answer to the card's begin. */
export function isWindowOpen(err) {
  return !!(err && err.status === 409 && err.body && err.body.code === "window_open");
}

/**
 * The card's begin body: `if_idle` asks the daemon to answer 409 window_open
 * (with that window's flow) instead of replacing a window that still works.
 */
export function beginBody(mode) {
  return { mode, if_idle: true };
}
