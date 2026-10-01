/*
 * Device-manager actions: poll now, refresh from providers, save tracked set.
 *
 * Purpose    : The three network-triggering buttons inside the Devices
 *              dialog, split out of devices.js (loop2 B2, PRI rule 7's
 *              300-line file cap -- devices.js was at 309).
 * Inputs     : Wired to their buttons by devices.js's wireDeviceControls().
 * Outputs    : POST /api/poll-now, /api/devices/refresh, /api/devices/track;
 *              re-renders the device modal and the dashboard on success.
 * Constraints: pollNow() and refreshFromProviders() are the only controls
 *              that query Google/Apple (devices.js's own file header claims
 *              this for the module as a whole, and still holds -- these are
 *              that module's controls, just not its file). Circular import
 *              with devices.js (for loadDevices/renderDeviceModal/
 *              closeDevices/providerWording) mirrors the existing
 *              main.js<->devices.js pattern already in this codebase: safe
 *              here because every use is inside a click handler, long after
 *              both modules have finished loading.
 */
"use strict";

import { $, state, showAlert } from "./state.js";
import { postJson } from "./api.js";
import { reload } from "./main.js";
import { t } from "./i18n.js";
import { shortStatus } from "./poll_status.js";
import { bannerRun, pollingMessage } from "./poll_cycle.js";
import { loadDevices, renderDeviceModal, closeDevices, providerWording } from "./devices.js";

// N50: mirrors MANUAL_POLL_COOLDOWN in cli/src/findplus/api/__init__.py. Used
// to disable the button for a successful poll, whose response carries no
// wait time of its own; a 429's own "Try again in {n}s" (routes_history.py)
// wins whenever one comes back, since the server's clock is the real one.
const POLL_COOLDOWN_MS = 60000;
const WAIT_SECONDS = /(\d+)s/;

/** Still cooling down from the last poll (this tab's own clock, a courtesy —
 * the server enforces the real cooldown regardless). */
let cooldownUntil = 0;
let cooldownTimer = null;

/** Disable the button for `ms`, then restore its normal label. A later call
 * (a 429 extending an already-running cooldown) replaces the pending timer
 * rather than stacking a second one. `data-cooling` (UAT7-N14) is the DOM
 * signal status_view.js's own syncTrackingActions() reads before it decides
 * whether nothing-tracked is the ONLY reason this button is disabled -- a
 * plain module import back into this file would cycle through main.js
 * (this file already imports reload() from there). */
function startCooldown(btn, ms) {
  cooldownUntil = Date.now() + ms;
  btn.disabled = true;
  btn.textContent = t("common.btnPoll");
  btn.dataset.cooling = "1";
  if (cooldownTimer) clearTimeout(cooldownTimer);
  cooldownTimer = setTimeout(() => {
    cooldownTimer = null;
    cooldownUntil = 0;
    delete btn.dataset.cooling;
    btn.disabled = false;
  }, ms);
}

/** The Devices dialog's own error line: the page banner sits behind the open dialog. */
function dialogError(text) {
  const line = $("device-modal-error");
  if (line) line.textContent = text;
}

/** Past this many trackers the result is counted by outcome, not listed one by one. */
const LIST_UP_TO = 4;

/** "12 no recent sighting · 3 not signed in": one count per outcome. */
function pollTally(results) {
  const counts = new Map();
  results.forEach((x) => counts.set(shortStatus(x.status), (counts.get(shortStatus(x.status)) || 0) + 1));
  return [...counts].map(([status, n]) => t("devices.pollTally", { n, status })).join(" · ");
}

/** The "N trackers polled" sentence: a line per tracker for a few, counts for many. */
function pollSummary(r) {
  if (r.results.length > LIST_UP_TO) {
    return t("devices.polledMany", { devices: r.devices_polled, observations: r.observations_new, tally: pollTally(r.results) });
  }
  const lines = r.results.map(
    (x) =>
      // UAT6-N06: plain words, never the raw status code.
      t("devices.pollResultLine", { device: x.device_name, status: shortStatus(x.status) }) +
      (x.observations_new ? t("devices.pollResultNew", { n: x.observations_new }) : "")
  );
  return t("devices.polled", {
    devices: r.devices_polled,
    observations: r.observations_new,
    lines: lines.join(" · "),
  });
}

/** Query every provider once, now, and say what came back.
 *
 * UAT5 N50: a second click within the server's one-per-minute limit used to
 * reach the API and come back 429, logging a console error even though the
 * on-screen message was already fine. The button now stays disabled for the
 * cooldown -- the server's own remaining wait on a 429, or this tab's guess
 * of the full window after a poll it made itself -- so a second click within
 * that window never fires a second request.
 */
export async function pollNow() {
  const btn = $("btn-poll");
  if (Date.now() < cooldownUntil) return;
  btn.disabled = true;
  btn.textContent = t("devices.pollingLabel");
  // Set before the request even starts (not just once startCooldown() runs
  // after it): `await reload()` below calls loadStatus() itself, and a
  // status_view.js resync mid-request must not read "not cooling" and
  // re-enable a button whose own request has not answered yet.
  btn.dataset.cooling = "1";
  // The API reports a poll only when it ends, so say it is under way from
  // here, and let status refreshes mid-request keep saying it.
  state.pollInFlight = true;
  const gen = state.lockGeneration;
  showAlert(pollingMessage(state.status), "info", { busy: true, hint: t("live.pollingHint") });
  try {
    const r = await postJson("/api/poll-now");
    state.pollInFlight = false;
    // The app locked while the request ran: the answer carries tracker names, and
    // the purge has already cleared the screen. Write nothing behind the lock.
    if (state.lockGeneration !== gen) return startCooldown(btn, POLL_COOLDOWN_MS);
    // Reload first: it redraws the banner, and a failure it names (locked,
    // signed out) must keep its action rather than be covered by this summary.
    await reload();
    // A lock during reload() has purged the screen again: still write nothing.
    if (state.lockGeneration === gen && (!state.status || !bannerRun(state.status))) {
      showAlert(pollSummary(r), "info");
    }
    startCooldown(btn, POLL_COOLDOWN_MS);
  } catch (err) {
    state.pollInFlight = false;
    if (state.lockGeneration === gen) showAlert(err.message, "err");
    if (err.status === 429) {
      const wait = WAIT_SECONDS.exec(err.message);
      startCooldown(btn, (wait ? Number(wait[1]) : 60) * 1000);
    } else {
      delete btn.dataset.cooling;
      btn.disabled = false;
      btn.textContent = t("common.btnPoll");
    }
  }
}

/**
 * Re-read the device list from every provider the user is signed in to.
 *
 * A partial failure names the provider that could not be reached rather than
 * staying silent, and the button says "your providers" whichever ones answered
 * (E1 honesty round 2 F4).
 */
export async function refreshFromProviders() {
  const btn = $("btn-refresh-devices");
  btn.disabled = true;
  btn.textContent = t("devices.askingProvidersLabel");
  dialogError("");
  try {
    const r = await postJson("/api/devices/refresh");
    await loadDevices();
    renderDeviceModal();
    const failed = Object.keys(r.errors || {});
    const msg = t("devices.refreshFound", { found: r.found, providers: (r.providers || []).length });
    if (failed.length) dialogError(msg + t("devices.refreshUnreachable", { names: failed.join(", ") }));
    else showAlert(msg, "warn");
  } catch (err) {
    dialogError(t("devices.refreshFailed", { message: err.message }));
  } finally {
    btn.disabled = false;
    btn.textContent = t("devices.refreshProvidersLabel");
  }
}

/** Save the ticked set and report the request rate it implies. */
export async function saveTrackedDevices() {
  const ids = [...document.querySelectorAll("#device-list input:checked")].map((i) => i.value);
  dialogError("");
  try {
    const r = await postJson("/api/devices/track", { device_ids: ids });
    closeDevices();
    await loadDevices();
    showAlert(
      r.tracked_count
        ? t("devices.trackedResult", {
            count: r.tracked_count,
            rate: r.requests_per_hour,
            requests: providerWording().requests,
          })
        : t("devices.trackedNone", { requests: providerWording().requests }),
      "warn"
    );
    await reload();
  } catch (err) {
    dialogError(err.message);
  }
}
