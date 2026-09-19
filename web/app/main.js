/*
 * findplus dashboard — entry point.
 *
 * Purpose : Render Find Hub observation history for one or many trackers as a
 *           map plus per-device chronological timelines.
 * Constraints:
 *   - Talks ONLY to this machine's local API. Refreshing this page never causes
 *     a Google query; the server polls Google on its own schedule.
 *   - No analytics, telemetry or third-party scripts. Leaflet is served locally.
 *   - This is the only file with DOMContentLoaded-adjacent boot logic; every
 *     other module is imported from here (directly or transitively).
 */
"use strict";

import { $, state, fmtTime, fmtDuration, todayLocal, applyTheme, showAlert } from "./state.js";
import { api } from "./api.js";
import { initMap } from "./map.js";
import { loadDay, selectPoint, wireTimelineControls, wireHistoryControls } from "./timeline.js";
import { loadDevices, openDevices, wireDeviceControls } from "./devices.js";
import { wireLockControls, refreshLockState, startIdleTimer } from "./lock.js";
import { wireSettingsControls, openSettings, loadSettings } from "./settings.js";

export async function loadStatus() {
  try {
    const s = await api(`/api/status${state.deviceFilter ? `?device_id=${encodeURIComponent(state.deviceFilter)}` : ""}`);

    const tracked = s.devices.filter((d) => d.is_tracked);
    $("device-name").textContent = state.deviceFilter
      ? (s.devices.find((d) => d.device_id === state.deviceFilter) || {}).name || state.deviceFilter
      : tracked.length
        ? `${tracked.length} device${tracked.length === 1 ? "" : "s"} tracked · ~${s.requests_per_hour}/hr`
        : "no devices tracked";

    const dot = $("live-dot");
    dot.className = "dot " + (s.poller_running ? "live" : "stale");
    dot.title = s.poller_running
      ? `Polling service active (every ${s.poll_interval_minutes} min)`
      : "No recent poll — the service may be stopped";

    const latest = s.latest_observation;
    if (latest) {
      $("card-observed").textContent = fmtTime(latest.observed_at_local);
      $("card-observed-ago").textContent = `${fmtDuration(latest.age_seconds)} ago · ${latest.device_name}`;
      $("card-fetched").textContent = fmtTime(latest.fetched_at_local);
      $("card-lag").textContent = `${fmtDuration(latest.retrieval_lag_seconds)} after it was seen`;
    } else {
      $("card-observed").textContent = "—";
      $("card-observed-ago").textContent = "no observations yet";
      $("card-fetched").textContent = "—";
      $("card-lag").textContent = "—";
    }

    const run = s.last_successful_poll;
    $("card-poll").textContent = run ? fmtTime(run.started_at_local) : "—";
    $("card-poll-status").textContent = s.last_poll ? `last attempt: ${s.last_poll.status}` : "no polls yet";
    $("card-today").textContent = String(s.observations_today);
    $("card-total").textContent = `${s.observations_total} total on record`;

    if (s.last_poll && !["ok", "no_location"].includes(s.last_poll.status)) {
      showAlert(`Last poll failed (${s.last_poll.status}): ${s.last_poll.error_message || "unknown error"}`, "err");
    } else if (!s.tracked_count) {
      showAlert('No devices are being tracked. Click "Devices" to choose which trackers to poll.', "warn");
    } else if (!s.poller_running) {
      showAlert("The polling service does not appear to be running. Start it with: findplus start", "warn");
    } else {
      showAlert(null);
    }
  } catch (err) {
    showAlert(`Could not reach the local API: ${err.message}`, "err");
  }
}

export async function loadConfig() {
  state.config = await api("/api/config");
  $("findhub-notice").textContent = state.config.notice;
  return state.config;
}

export async function reload() {
  await loadStatus();
  await loadDay(state.day);
}

export function closeModals() {
  $("device-modal").classList.add("hidden");
  $("settings-modal").classList.add("hidden");
}

/** `#settings` and `#devices` deep-link straight to a dialog. */
export async function applyHashRoute() {
  if (state.locked) return;
  const hash = window.location.hash;
  if (hash === "#settings") await openSettings();
  else if (hash === "#devices") await openDevices();
  else closeModals();
}

function wireControls() {
  wireDeviceControls();
  wireTimelineControls();
  wireHistoryControls();
  wireLockControls();
  wireSettingsControls();
}

/**
 * Load everything the dashboard needs and start its timers.
 *
 * Called both on a normal (unlocked) start AND after an unlock. Starting locked
 * used to skip this entirely, which left `state.config` null (breaking the
 * Settings dialog), the Find Hub notice blank, and the auto-refresh timer never
 * created for the rest of the session.
 */
export async function bootDashboard(resume) {
  const config = await loadConfig();
  await loadSettings();
  await loadDevices();

  if (resume) {
    state.deviceFilter = resume.deviceFilter;
    state.movementOnly = resume.movementOnly;
    $("device-filter").value = resume.deviceFilter || "";
    $("toggle-movement").checked = resume.movementOnly;
  }

  await loadStatus();
  await loadDay((resume && resume.day) || todayLocal());

  if (resume && resume.selectedId) selectPoint(resume.selectedId, true);
  if (resume) window.scrollTo(0, resume.scrollY);

  startIdleTimer();
  await applyHashRoute();

  // Polls the LOCAL API only. Google is queried server-side on its own interval.
  // Guarded so repeated lock/unlock cycles cannot stack duplicate timers.
  if (state.refreshTimer) clearInterval(state.refreshTimer);
  const seconds = Math.max(30, config.ui_refresh_seconds || 45);
  state.refreshTimer = setInterval(async () => {
    if (state.locked) return;  // never poll the API from behind the lock screen
    try {
      await loadStatus();
      if (state.day === todayLocal()) await loadDay(state.day);
    } catch (_) { /* a lock mid-refresh is handled by api() */ }
  }, seconds * 1000);
}

async function main() {
  // Paint the cached theme before anything else so there is no flash.
  applyTheme(localStorage.getItem("bt.theme") || "dark");

  initMap();
  wireControls();

  // Ask about the lock BEFORE requesting any location data.
  if (await refreshLockState()) return;

  await bootDashboard(null);
}

main();
