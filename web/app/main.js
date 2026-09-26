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

import { $, state, todayLocal, applyTheme, showAlert, getStoredTheme } from "./state.js";
import { api } from "./api.js";
import { initMap, setDefaultView } from "./map.js";
import { loadDay, selectPoint, wireTimelineControls, wireHistoryControls } from "./timeline.js";
import { loadDevices, openDevices, wireDeviceControls } from "./devices.js";
import { wireLockControls, refreshLockState, startIdleTimer } from "./lock.js";
import { wireSettingsControls, openSettings, loadSettings } from "./settings.js";
import { loadCatalog, applyStaticI18n, t } from "./i18n.js";
import { loadStatus } from "./status_view.js";
import { initTabbar } from "./components/tabbar.js";
import { wireTabsKeyboard } from "./components/tabs_a11y.js";
import { openSetupRoute, closeSetupRoute, checkOnboarding } from "./setup_route.js";
import { loadIconSprite } from "./icon_sprite.js";

// The status chrome (device name, service dot, cards, banner) lives in
// status_view.js; re-exported so existing `main.js` importers keep working.
export { loadStatus };

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
 * `closeOthers` is false on the boot call: bootDashboard() awaits loadStatus()
 * and loadDay() first while the toolbar stays live, so a user (or test) who
 * clicked Devices during boot had it closed right back by this function (CI-2,
 * run 35530635344: "62 x locator resolved to hidden"). Closing belongs to a
 * real hashchange away from a dialog, not to boot.
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
 * Runs on a normal start AND after unlock -- starting locked used to skip
 * this, leaving `state.config` null and the auto-refresh timer never created.
 */
export async function bootDashboard(resume) {
  state.dashboardBooted = true;
  // Cleared here, set at the end: runs again on unlock, and a stale "ready"
  // must not out-run THIS call (alerts.js's data-fp-ready convention).
  delete $("app-shell").dataset.fpReady;
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

  // lock.js's unlock flow fires this unawaited, so a click elsewhere can land
  // before the alert banner or map fit above render. Ready-when-done signal.
  $("app-shell").dataset.fpReady = "dashboard";
}

async function main() {
  // Fire-and-forget: every consumer runs from a dialog opened long after this
  // settles, and a missing sprite must not stop the dashboard booting.
  loadIconSprite().catch(() => {});
  // Paint the cached theme before anything else so there is no flash.
  applyTheme(getStoredTheme());

  // Before the first await on purpose: after `await loadCatalog()`, an early
  // click on #btn-settings landed unwired and was lost (CI run 36250697463).
  initMap();
  wireControls();

  // One walk over the document (the daemon composed the shell and all five
  // partials into this page already) renders every data-i18n element.
  await loadCatalog();
  applyStaticI18n();
  // Needs the catalog labels and static markup, so it runs after applyStaticI18n().
  initTabbar();

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
