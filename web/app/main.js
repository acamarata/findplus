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

import { $, state, fmtTime, fmtDuration, todayLocal, applyTheme, showAlert, getStoredTheme } from "./state.js";
import { api } from "./api.js";
import { initMap, setDefaultView } from "./map.js";
import { loadDay, selectPoint, wireTimelineControls, wireHistoryControls } from "./timeline.js";
import { loadDevices, openDevices, wireDeviceControls } from "./devices.js";
import { wireLockControls, refreshLockState, startIdleTimer } from "./lock.js";
import { wireSettingsControls, openSettings, loadSettings } from "./settings.js";
import { loadCatalog, applyStaticI18n, t, plural } from "./i18n.js";
import { initTabbar } from "./components/tabbar.js";
import { wireTabsKeyboard } from "./components/tabs_a11y.js";
import { openSetupRoute, closeSetupRoute, checkOnboarding } from "./setup_route.js";
import { loadIconSprite } from "./icon_sprite.js";

/** The topbar device name: the filtered tracker, or how many are tracked.
 * U30: the title tooltip spells out what "~72/hr" counts. */
function renderDeviceName(s) {
  const tracked = s.devices.filter((d) => d.is_tracked);
  const el = $("device-name");
  el.title = "";
  if (state.deviceFilter) {
    el.textContent = (s.devices.find((d) => d.device_id === state.deviceFilter) || {}).name || state.deviceFilter;
    return;
  }
  if (!tracked.length) { el.textContent = t("common.noDevicesTracked"); return; }
  el.textContent = plural("common.devicesTracked", tracked.length, { n: tracked.length, rate: s.requests_per_hour });
  el.title = t("common.devicesTrackedRateHint", { rate: s.requests_per_hour });
}

/** The service dot: colour plus a tooltip saying what the colour means. */
function renderPollerDot(s) {
  const dot = $("live-dot");
  dot.className = "dot " + (s.poller_running ? "live" : "stale");
  dot.title = s.poller_running
    ? t("common.pollerActive", { interval: s.poll_interval_minutes })
    : t("common.pollerStale");
}

/** The four summary cards. With no observation yet every value reads as empty. */
function renderCards(s) {
  const latest = s.latest_observation;
  if (latest) {
    $("card-observed").textContent = fmtTime(latest.observed_at_local);
    $("card-observed-ago").textContent = t("common.observedAgo", {
      age: fmtDuration(latest.age_seconds),
      device: latest.device_name,
    });
    $("card-fetched").textContent = fmtTime(latest.fetched_at_local);
    $("card-lag").textContent = t("common.retrievalLag", {
      lag: fmtDuration(latest.retrieval_lag_seconds),
    });
  } else {
    $("card-observed").textContent = t("common.emptyValue");
    $("card-observed-ago").textContent = t("common.noObservationsYet");
    $("card-fetched").textContent = t("common.emptyValue");
    $("card-lag").textContent = t("common.emptyValue");
  }

  const run = s.last_successful_poll;
  $("card-poll").textContent = run ? fmtTime(run.started_at_local) : t("common.emptyValue");
  $("card-poll-status").textContent = s.last_poll
    ? t("common.lastAttempt", { status: s.last_poll.status })
    : t("common.noPollsYet");
  $("card-today").textContent = String(s.observations_today);
  $("card-total").textContent = t("common.totalOnRecord", { total: s.observations_total });
}

/** The banner, in priority order: a failed poll, nothing tracked, a stopped service. */
function renderStatusAlert(s) {
  if (s.last_poll && !["ok", "no_location"].includes(s.last_poll.status)) {
    const message = s.last_poll.error_message || t("common.unknownError");
    showAlert(t("common.pollFailed", { status: s.last_poll.status, message }), "err");
  } else if (!s.tracked_count) {
    showAlert(t("common.nothingTracked"), "warn");
  } else if (!s.poller_running) {
    showAlert(t("common.serviceNotRunning"), "warn");
  } else {
    showAlert(null);
  }
}

export async function loadStatus() {
  try {
    const query = state.deviceFilter ? `?device_id=${encodeURIComponent(state.deviceFilter)}` : "";
    const s = await api(`/api/status${query}`);
    renderDeviceName(s);
    renderPollerDot(s);
    renderCards(s);
    renderStatusAlert(s);
  } catch (err) {
    showAlert(t("common.apiUnreachable", { message: err.message }), "err");
  }
}

let configLoad = null;

/** Fetch /api/config, sharing one in-flight request so a caller racing
 *  bootDashboard() (openSettings(), openSetupRoute()) never double-fetches
 *  (CI run 35546305331). Clears once settled, so a later call still refetches. */
export function loadConfig() {
  configLoad ??= api("/api/config").then((c) => (state.config = c)).finally(() => (configLoad = null));
  return configLoad;
}

export async function reload() {
  await loadStatus();
  await loadDay(state.day);
}

export function closeModals() {
  $("device-modal").classList.add("hidden");
  $("settings-modal").classList.add("hidden");
}

/**
 * `#settings` and `#devices` deep-link straight to a dialog.
 *
 * `closeOthers` is false on the boot call. bootDashboard() awaits loadStatus()
 * and loadDay() first, both network round trips, while the toolbar is already
 * live — so a user (or a test) who clicked Devices during boot had the dialog
 * opened and then closed again by this function, leaving the rows rendered but
 * invisible with nothing on screen to explain it. That is CI-2, CI run
 * 35530635344: "62 x locator resolved to hidden". At boot there is nothing to
 * close anyway; the markup starts hidden. Closing belongs to a real hashchange
 * away from a dialog.
 */
export async function applyHashRoute({ closeOthers = true } = {}) {
  if (state.locked) return;
  const hash = window.location.hash;
  if (hash === "#/setup") {
    await openSetupRoute();
    return;
  }
  // Anything that is not #/setup leaves the wizard: the route must not be
  // enterable-but-not-leavable (CR-C-E11 F2).
  await closeSetupRoute();
  if (hash === "#settings") await openSettings();
  else if (hash === "#devices") await openDevices();
  // The Places widget's tap target (findplus://places -> windows::open_places
  // -> this hash): switch to the tab the widget promises, rather than leaving
  // the dashboard on whatever tab was last active.
  else if (hash === "#places") switchTab("places");
  // The wizard's Notifications step "configure later" webhook link (UAT
  // U17): it used to point at "#settings", a dead end since webhook setup
  // lives in the Alerts tab, not Settings.
  else if (hash === "#alerts-webhook") {
    switchTab("alerts");
    $("fp-webhook-section")?.scrollIntoView({ block: "start" });
  } else if (closeOthers) closeModals();
}

/**
 * Switch the active `.fp-tab` / `.fp-tab-panel` pair.
 *
 * The one place tab switching happens: the top nav's buttons and the phone
 * tier's bottom tab bar (components/tabbar.js) both call this rather than
 * keeping two copies of the toggling.
 */
export function switchTab(tab) {
  document.querySelectorAll(".fp-tabs .fp-tab").forEach((b) => {
    const active = b.dataset.tab === tab;
    b.classList.toggle("active", active);
    // WAI-ARIA tabs (U31): only the active tab is a Tab stop (tabs_a11y.js).
    b.setAttribute("aria-selected", String(active));
    b.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll(".fp-tab-panel").forEach((p) => {
    p.hidden = p.id !== "tab-" + tab;
  });
}

function wireTabs() {
  document.querySelectorAll(".fp-tabs .fp-tab").forEach((btn) =>
    btn.addEventListener("click", () => switchTab(btn.dataset.tab)));
  wireTabsKeyboard(switchTab);
}

function wireControls() {
  wireTabs();
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
  state.dashboardBooted = true;
  const config = await loadConfig();
  await loadSettings({ renderDialog: false });
  await loadDevices();
  // U4: fit the map to real data (tracked devices' latest fixes, else saved
  // places, else a world view) before the day-specific fit below runs. A day
  // with nothing in it leaves this in place instead of the old US default.
  await setDefaultView().catch(() => {});

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
  await applyHashRoute({ closeOthers: false });

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
  // Fire-and-forget: every consumer (icon picker, badge renderer) runs from a
  // dialog the user opens long after this settles, and a missing sprite must
  // not stop the dashboard booting.
  loadIconSprite().catch(() => {});
  // Paint the cached theme before anything else so there is no flash.
  applyTheme(getStoredTheme());

  // The catalog has no DOM dependency, so it can be loaded first; then ONE walk
  // over the document renders every data-i18n element. The daemon composed the
  // shell and all five partials into this page before serving it, so that one
  // walk covers the whole UI and nothing added later needs a second hook.
  await loadCatalog();
  applyStaticI18n();
  // Needs the catalog (its labels) and the static markup (#btn-more), so it
  // runs after applyStaticI18n() and before the rest of the boot sequence.
  initTabbar();

  initMap();
  wireControls();

  // UAT2 N12: ask about the lock first (a public GET) so state.locked is set
  // before Places/Groups/Alerts wire up below -- each checks it and skips its
  // own fetch while locked, rather than firing and 401ing. init() still runs
  // either way: it does one-time DOM/map wiring too, which refreshTabsAfterUnlock() needs already done.
  const locked = await refreshLockState();
  if (!locked) import("./notices.js").then((m) => m.loadNotices()).catch(() => {});

  // Places tab: draws saved geofence circles and injects presence chips into
  // device rows. Awaited: the wizard's Places step borrows this module's
  // dialog and map, and the onboarding check below can redirect into it.
  const deviceList = document.getElementById("device-list");
  await import("./places.js").then((m) => m.init(state.map, deviceList));
  // Groups tab: coloured member overlays and the presence panel. Wired here
  // (not in P1-E10-W6-S1-T2's own file list) — without a real map instance
  // the Groups tab has nothing to bind its selector or overlay layer to.
  await import("./groups.js").then((m) => m.init(state.map, deviceList));
  await import("./alerts.js").then((m) => m.init());
  if (locked) return;

  // A never-onboarded install goes to the wizard; one that navigated
  // elsewhere gets the banner instead.
  if (await checkOnboarding()) return;

  await bootDashboard(null);
}

// Boot is one async chain and nothing above awaits it. An unguarded rejection
// here surfaces only as a console page error, which tells the user nothing and
// trips the browser suite's no-page-errors assertion; the banner at least says
// what failed.
main().catch((err) => {
  showAlert(t("common.apiUnreachable", { message: err.message }), "err");
});
