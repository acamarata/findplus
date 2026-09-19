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
export async function showLock() {
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
  await purgeRenderedData();
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
export async function purgeRenderedData() {
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

  await purgeTabModules();
}

/**
 * Purge the Places, Groups and Alerts tabs' own rendered state.
 *
 * Each of those modules keeps a Leaflet overlay layer and/or DOM (place
 * circles, group-member circles, the presence panel, the group legend and
 * select, the alerts rules table) outside anything the code above already
 * clears — reviewer-E10 measured real coordinates and names still present
 * in `.leaflet-overlay-pane` and those elements after a lock. Dynamic
 * import reaches the already-loaded module instances (matching
 * refreshTabsAfterUnlock()'s pattern below); each purge is independent so
 * one module throwing never leaves another module's data behind.
 */
async function purgeTabModules() {
  const results = await Promise.allSettled([
    import("./places.js").then((m) => m.purge()),
    import("./groups.js").then((m) => m.purge()),
    import("./alerts.js").then((m) => m.purge()),
  ]);
  results.forEach((r) => {
    if (r.status === "rejected") console.error("post-lock purge failed", r.reason);
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
  await refreshTabsAfterUnlock();
}

/**
 * Reload the Places, Groups, Alerts tabs and the honesty notices after an
 * unlock.
 *
 * Those four modules load their data once, at page-parse time, via a
 * dynamic import in main.js (places.js, groups.js) or their own top-level
 * `<script type="module">` tag (alerts.js, notices.js) — before this
 * session's lock state is known. A session that boots locked never
 * repopulates them once unlocked (notices.js's six #fp-notice-* paragraphs
 * would stay blank all session — PROMPT.md §2 invariant 4 requires honesty
 * text actually render, not just be fetchable), since nothing else calls
 * their loaders again. Dynamic import here (matching main.js's own "keeps
 * it optional at parse time" pattern) reaches the already-loaded module
 * instances without re-running their one-time init() — ES modules are
 * singletons per URL — and each loader is independent so one tab's failure
 * never blocks the others.
 */
async function refreshTabsAfterUnlock() {
  const results = await Promise.allSettled([
    import("./places.js").then((m) => m.refreshAll()),
    import("./groups.js").then((m) => m.refreshPresence()),
    import("./alerts.js").then((m) => m.refreshAll()),
    import("./notices.js").then((m) => m.loadNotices()),
  ]);
  results.forEach((r) => {
    if (r.status === "rejected") console.error("post-unlock tab refresh failed", r.reason);
  });
}

export async function refreshLockState() {
  try {
    const st = await api("/api/lock/status");
    state.idleMinutes = st.idle_minutes;
    $("btn-lock").classList.toggle("hidden", !st.lock_configured || !st.lock_enabled);
    if (st.theme) applyTheme(st.theme);
    if (st.locked) { await showLock(); return true; }
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
  await showLock();
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
