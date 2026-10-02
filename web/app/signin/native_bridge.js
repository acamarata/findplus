/*
 * The desktop app's bridge, seen from the sign-in cards.
 *
 * Purpose    : One place that knows whether this page runs inside the Find+
 *              desktop app with a usable Tauri bridge, and how to call the
 *              shell's `open_signin_window` command and hear its events
 *              (signin-progress, signin-result, signin-apple-sheet,
 *              auth-attention). Contract: specs/in-app-login-contract.md and
 *              the 12a shell report.
 * Inputs     : window.__findplus_native (set only by the app's init script)
 *              and window.__TAURI__ (withGlobalTauri).
 * Outputs    : hasNativeWindow(), openSigninWindow(), closeSigninWindow(),
 *              listenNative().
 * Constraints: Feature-detects every piece: a plain browser tab, an older app
 *              without the command, or a bridge without `event.listen` all
 *              fall back to the browser flows. Nothing here ever opens a
 *              browser, Finder or Chrome on its own.
 */
"use strict";

/** The Tauri bridge, or null outside the desktop app. */
function tauri() {
  if (window.__findplus_native !== true) return null;
  const bridge = window.__TAURI__;
  return bridge && bridge.core && typeof bridge.core.invoke === "function" ? bridge : null;
}

/** True when the card can open the Find+ sign-in window. */
export function hasNativeWindow() {
  return tauri() !== null;
}

/**
 * Ask the shell to open (or focus) its sign-in window.
 *
 * `begin` is the card's own POST .../native/begin reply, so the window works
 * behind the app lock too; omit it for "Show window", which only focuses an
 * open window. Resolves with "opened", "already_open" or "apple_sheet".
 */
export function openSigninWindow(provider, mode, begin) {
  const bridge = tauri();
  if (!bridge) return Promise.reject(new Error("no_native_bridge"));
  const args = { provider, mode };
  if (begin) args.begin = begin;
  return bridge.core.invoke("open_signin_window", args);
}

/** Ask the shell to close its Google window (best effort; never throws). */
export function closeSigninWindow() {
  const bridge = tauri();
  if (!bridge) return;
  Promise.resolve()
    .then(() => bridge.core.invoke("close_signin_window", { provider: "google" }))
    .catch(() => {});
}

/**
 * Listen to one shell event; resolves with an unlisten function (a no-op
 * when the bridge has no event API, so callers never branch on it).
 */
export async function listenNative(name, handler) {
  const bridge = tauri();
  const listen = bridge && bridge.event && bridge.event.listen;
  if (typeof listen !== "function") return () => {};
  try {
    const unlisten = await listen.call(bridge.event, name, (event) =>
      handler(event && "payload" in event ? event.payload : event)
    );
    return typeof unlisten === "function" ? unlisten : () => {};
  } catch (_err) {
    return () => {};
  }
}
