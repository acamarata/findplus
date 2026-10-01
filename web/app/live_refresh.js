/*
 * The dashboard's own heartbeat: notice a change and redraw, no reload needed.
 *
 * Purpose    : After an unlock or sign-in the server polls on its own, but the
 *              page sat on its old banner, empty tiles and empty map until the
 *              next 45-second timer, and then refreshed only today's timeline.
 *              This module reads /api/status (the existing poll-status
 *              mechanism, local only) on a cadence that follows what is going
 *              on, and when the poll or the account changed it reloads the
 *              device list, the day and the map as well.
 * Inputs     : GET /api/status through status_view.js's loadStatus();
 *              "findplus:accounts-changed" from the sign-in panel;
 *              ui_refresh_seconds from /api/config.
 * Outputs    : A redrawn banner, tiles, device list, timeline and map.
 * Constraints: Local API only; it never asks Google. Idle while locked or the
 *              tab is hidden (one catch-up refresh when the tab returns). One
 *              timer chain, so repeated unlock cycles cannot stack timers. A
 *              lock mid-refresh drops the result (state.lockGeneration).
 *              Cadence: SLOW (the configured refresh) when all is well, ATTENTION
 *              while the dashboard shows a problem the user is fixing, WAITING
 *              while a poll is expected or running.
 */
"use strict";

import { state, todayLocal } from "./state.js";
import { loadStatus } from "./status_view.js";
import { loadDay } from "./timeline.js";
import { loadDevices } from "./devices.js";
import { setDefaultView } from "./map.js";
import { anyProviderSignedIn, resetSignedInCache } from "./poll_status.js";
import { bannerRun } from "./poll_cycle.js";

/** Cadences (ms). SLOW is replaced by ui_refresh_seconds at start. */
export const WAITING_MS = 3000;
export const ATTENTION_MS = 10000;
let slowMs = 45000;

let timer = null;
let lastSignature = null;
let started = false;
/** Bumped by stopLiveRefresh(): a look still in flight then must not re-arm the old chain. */
let chain = 0;

/** What changes when there is something new to draw. */
export function signature(s) {
  const id = (run) => (run ? run.id : null);
  const latest = s.latest_observation;
  return [
    id(s.last_poll), s.last_poll && s.last_poll.status, id(s.last_successful_poll),
    s.tracked_count, s.observations_total, latest && latest.observed_at_utc,
  ].join("|");
}

/** How long to wait before the next look. */
function nextDelay(s) {
  if (state.awaitingPoll || state.pollInFlight) return WAITING_MS;
  if (s && bannerRun(s)) return ATTENTION_MS;
  return slowMs;
}

/** New data arrived: reload the lists, the day and, if the map was bare, its view. */
async function refreshData(gen) {
  await loadDevices();
  if (state.lockGeneration !== gen) return false;
  await loadDay(state.day || todayLocal());
  if (state.lockGeneration !== gen) return false;
  if (!state.markers.size) await setDefaultView().catch(() => {});
  return true;
}

/**
 * One look at the status; redraw everything when it changed.
 *
 * With `fast`, the day is reloaded only on a change (a status read is cheap, a
 * timeline is not); otherwise today is re-read each time, as the old timer did.
 */
export async function refreshOnce({ fast = false } = {}) {
  const gen = state.lockGeneration;
  const s = await loadStatus();
  if (!s || state.lockGeneration !== gen) return s;
  const sig = signature(s);
  const changed = lastSignature !== null && sig !== lastSignature;
  if (lastSignature === null) lastSignature = sig;
  // The change counts as seen only once the redraw finished: a failed or
  // lock-cancelled refresh is retried on the next look, not lost.
  if (changed) {
    if (await refreshData(gen)) lastSignature = sig;
  } else if (!fast && state.day === todayLocal()) await loadDay(state.day);
  return s;
}

function schedule(s) {
  if (timer) clearTimeout(timer);
  timer = setTimeout(tick, nextDelay(s));
}

async function tick() {
  timer = null;
  const mine = chain;
  let s = state.status;
  if (!state.locked && !document.hidden) {
    try {
      s = await refreshOnce({ fast: nextDelay(state.status) < slowMs });
    } catch (_) { /* a lock mid-refresh is handled by api() */ }
  }
  if (mine === chain) schedule(s);
}

/** Wait for the poll an unlock or sign-in is about to trigger. */
export function expectPoll(s) {
  state.awaitingPoll = { since: Date.now(), baseId: s.last_poll ? s.last_poll.id : null, n: s.tracked_count };
}

/** An account was signed in, unlocked or removed: look now, then watch closely. */
async function onAccountsChanged() {
  if (!started || state.locked) return;
  const gen = state.lockGeneration; // a lock during these awaits must not leave "Polling..." behind
  resetSignedInCache();
  const s = await refreshOnce({ fast: true });
  if (state.lockGeneration !== gen) return;
  if (!s || !s.tracked_count) return schedule(s);
  const signedIn = await anyProviderSignedIn();
  if (state.lockGeneration !== gen) return;
  if (signedIn) {
    expectPoll(s);
    await loadStatus();  // draws "Polling N trackers…" at once
  }
  schedule(state.status);
}

/** A tab that was hidden catches up the moment it is visible again. */
function onVisible() {
  if (!document.hidden && started && !state.locked) {
    if (timer) clearTimeout(timer);
    tick();
  }
}

/**
 * (Re)start the heartbeat. Safe to call on every boot and unlock: one timer
 * chain, and the listeners are added once.
 */
export function startLiveRefresh(seconds) {
  slowMs = seconds * 1000;
  lastSignature = state.status ? signature(state.status) : null;
  if (!started) {
    window.addEventListener("findplus:accounts-changed", onAccountsChanged);
    document.addEventListener("visibilitychange", onVisible);
  }
  started = true;
  schedule(state.status);
}

/** Lock: stop the chain; the unlock boot starts a fresh one. */
export function stopLiveRefresh() {
  if (timer) clearTimeout(timer);
  timer = null;
  chain++;
  lastSignature = null;
  state.awaitingPoll = null;
}
