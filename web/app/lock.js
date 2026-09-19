/*
 * App lock: the lock screen, PIN submission, the idle timer, and the DOM
 * purge that is a PROMPT.md invariant.
 *
 * Purpose    : Show/hide the lock screen and guarantee no location data
 *              survives on screen once the app is locked.
 * Constraints: purgeRenderedData() must destroy — not merely hide — every
 *              rendered coordinate and place name; it runs on every 401 and
 *              whenever the lock screen is shown. This is a security
 *              invariant (PROMPT.md §2), not a style choice.
 */
"use strict";

import { $, state, applyTheme } from "./state.js";
import { postJson, api } from "./api.js";
import { closeModals, bootDashboard } from "./main.js";

/**
 * Show the lock screen.
 *
 * The dashboard is removed from the document flow, not merely covered, and the
 * server independently refuses every gated API call while locked — so this is
 * not a cosmetic overlay that a determined person could scroll behind.
 * The current view is captured first so unlocking returns to exactly it.
 */
export function showLock() {
  if (!state.locked) {
    // Only non-sensitive view state is remembered — a date, a device filter and
    // a row id. No coordinates are retained anywhere once locked.
    state.resume = {
      day: state.day,
      deviceFilter: state.deviceFilter,
      selectedId: state.selectedId,
      movementOnly: state.movementOnly,
      scrollY: window.scrollY,
    };
  }
  state.locked = true;
  stopIdleTimer();
  closeModals();
  purgeRenderedData();
  $("app-shell").classList.add("hidden");
  $("lock-screen").classList.remove("hidden");
  $("lock-error").textContent = "";
  $("lock-pin").value = "";
  $("lock-pin").focus();
}

/**
 * Remove every rendered coordinate from the page.
 *
 * Hiding `#app-shell` stops it being *displayed*, but the markup would still sit
 * in the DOM where View Source or DevTools could read the last-viewed history.
 * The API refusing to answer is not enough on its own — what was already
 * delivered has to be destroyed too.
 */
export function purgeRenderedData() {
  state.timeline = null;
  state.devices = [];
  state.selectedId = null;
  state.markers.clear();
  if (state.layer) state.layer.clearLayers();
  if (state.map) state.map.setView([39.5, -98.35], 4);

  $("tracks").innerHTML = "";
  $("device-list").innerHTML = "";
  $("device-filter").innerHTML = '<option value="">All tracked devices</option>';
  $("device-name").textContent = "";
  $("alert").classList.add("hidden");
  $("alert").textContent = "";
  ["card-observed", "card-observed-ago", "card-fetched", "card-lag",
   "card-poll", "card-poll-status", "card-today", "card-total"].forEach((id) => {
    $(id).textContent = "—";
  });
}

/** Hide the lock screen and restore the exact view the user was on. */
export async function hideLockAndRestore() {
  state.locked = false;
  $("lock-screen").classList.add("hidden");
  $("app-shell").classList.remove("hidden");

  const resume = state.resume;
  state.resume = null;

  // Full boot, not a partial refresh: after an unlock the session may never
  // have loaded config/settings at all.
  await bootDashboard(resume);
}

export async function refreshLockState() {
  try {
    const st = await api("/api/lock/status");
    state.idleMinutes = st.idle_minutes;
    $("btn-lock").classList.toggle("hidden", !st.lock_configured || !st.lock_enabled);
    if (st.theme) applyTheme(st.theme);
    if (st.locked) { showLock(); return true; }
    return false;
  } catch (_) {
    return false;
  }
}

export async function submitPin(pin) {
  const err = $("lock-error");
  const btn = $("lock-submit");
  btn.disabled = true;
  try {
    await postJson("/api/lock/unlock", { pin });
    err.textContent = "";
    await hideLockAndRestore();
  } catch (e) {
    err.textContent = e.message;
    $("lock-pin").value = "";
    $("lock-pin").focus();
  } finally {
    btn.disabled = false;
  }
}

export async function lockNow() {
  try { await postJson("/api/lock/lock"); } catch (_) {}
  showLock();
}

/* ------------------------------------------------------------ idle timer */

export function startIdleTimer() {
  stopIdleTimer();
  if (!state.idleMinutes) return;  // 0 = never auto-lock
  state.idleTimer = setTimeout(lockNow, state.idleMinutes * 60 * 1000);
}

export function stopIdleTimer() {
  if (state.idleTimer) { clearTimeout(state.idleTimer); state.idleTimer = null; }
}

export function noteActivity() {
  if (state.locked || !state.idleMinutes) return;
  startIdleTimer();
}

/** Wire the lock form, the manual lock button, and the idle-activity listeners. */
export function wireLockControls() {
  $("lock-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const pin = $("lock-pin").value.trim();
    if (pin) submitPin(pin);
  });
  $("btn-lock").addEventListener("click", lockNow);

  // Any interaction postpones the idle auto-lock.
  ["mousemove", "keydown", "click", "scroll", "touchstart"].forEach((evt) => {
    window.addEventListener(evt, noteActivity, { passive: true });
  });
}
