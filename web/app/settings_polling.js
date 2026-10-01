/*
 * Settings dialog -- polling, retention and start-at-login controls.
 *
 * Purpose    : Split out of settings.js (PRI rule 7, 300-line file cap):
 *              adding the UAT U19 field-level poll-interval validation
 *              pushed settings.js past the cap.
 * Inputs     : #setting-poll-interval(-error), #setting-retention-days,
 *              #setting-start-at-login, #setting-native-detail(-row/-note),
 *              state.settings/state.config.
 * Outputs    : renderPollingSection() (called from settings.js's
 *              loadSettings()) and wirePollingControls() (called from
 *              wireSettingsControls()).
 * Constraints: Takes settings.js's own saveSettings()/showSettingsMessage()
 *              as parameters rather than importing them back, so the two
 *              files never import each other.
 */
"use strict";

import { $, state } from "./state.js";
import { postJson } from "./api.js";
import { t, plural } from "./i18n.js";

const MIN_RETENTION_DAYS = 7;

/** How many devices Find+ polls: the status count, else the device list's tracked rows. */
function trackedCount() {
  if (state.status && Number.isInteger(state.status.tracked_count)) return state.status.tracked_count;
  return (state.devices || []).filter((d) => d.is_tracked).length;
}

/**
 * The requests-per-hour consequence of the interval in the box (UAT: the
 * owner should see the cost of "5 minutes" before choosing it). Same formula as
 * the header's "~N/hr": tracked devices x 60 / minutes.
 */
export function renderPollRate() {
  const el = $("setting-poll-rate");
  if (!el) return;
  const n = Number($("setting-poll-interval").value);
  if (!Number.isInteger(n) || n < 5 || n > 1440) { el.textContent = ""; return; }
  const count = trackedCount();
  if (!count) { el.textContent = t("settings.polling.rateNone"); return; }
  const rate = Math.round((count * 60 * 10) / n) / 10;
  const base = plural("settings.polling.rate", count, { rate, count });
  el.textContent = n < 10 ? `${base} ${t("settings.polling.rateFast")}` : base;
}

/** What the retention box means right now, in one sentence; blank keeps everything. */
export function renderRetentionEffect() {
  const el = $("setting-retention-effect");
  if (!el) return;
  const raw = $("setting-retention-days").value;
  const days = Number(raw);
  if (raw === "") el.textContent = t("settings.polling.retentionKeepAll");
  else if (Number.isInteger(days) && days >= MIN_RETENTION_DAYS) {
    el.textContent = t("settings.polling.retentionDays", { days });
  } else el.textContent = "";
}

function showRetentionError(show) {
  const el = $("setting-retention-error");
  if (el) el.classList.toggle("hidden", !show);
  $("setting-retention-days").setAttribute("aria-invalid", String(!!show));
}

/** The poll-interval field's own error line (UAT U19), next to the input
 * rather than the top-of-dialog #settings-message. `show` false clears it. */
function showPollIntervalError(show) {
  const el = $("setting-poll-interval-error");
  if (!el) return;
  el.classList.toggle("hidden", !show);
  $("setting-poll-interval").setAttribute("aria-invalid", String(!!show));
}

/**
 * True (and no field error) for a value the server will also accept.
 *
 * Mirrors config_keys.py's 5-1440 range so a bad value never reaches the
 * server at all; the server's own 422 (a stale env var, a second tab) is
 * still mapped to this same friendly wording below, in case it disagrees.
 */
function validatePollInterval(value) {
  const n = Number(value);
  const ok = Number.isInteger(n) && n >= 5 && n <= 1440;
  showPollIntervalError(!ok);
  return ok;
}

/**
 * Poll interval, history retention and the native-detail toggle.
 *
 * The toggle and its sentence only exist in the desktop app:
 * `window.__findplus_native` is set by an initialization script on the Tauri
 * window and by nothing else (R-P2-13), so a browser tab at :8647 never shows
 * a control for notifications it cannot deliver. The sentence beside it is
 * replaced with the live one from /api/config, which always beats the
 * catalog's bootstrap copy.
 */
export function renderPollingSection() {
  showPollIntervalError(false); // never a stale rejection from a previous open
  $("setting-poll-interval").value = state.settings["poll.interval_minutes"];
  $("setting-retention-days").value = state.settings["history.retention_days"] ?? "";
  showRetentionError(false);
  renderPollRate();
  renderRetentionEffect();
  if (window.__findplus_native !== true) return;
  $("setting-native-detail-row").hidden = false;
  $("setting-native-detail-note").hidden = false;
  $("setting-native-detail").checked = state.settings["alerts.native_detail"];
  if (state.config && state.config.notices) {
    $("setting-native-detail-note").textContent = state.config.notices.native_generic;
  }
}

/**
 * Start-at-login, poll interval, retention, and the native-detail toggle.
 *
 * `saveSettings` and `showSettingsMessage` are settings.js's own, passed in
 * rather than imported, so this stays a leaf module.
 */
export function wirePollingControls(saveSettings, showSettingsMessage, markSaved) {
  $("setting-start-at-login").addEventListener("change", async (e) => {
    try {
      await postJson("/api/settings/app.start_at_login", { value: e.target.checked });
      markSaved();
    } catch (err) {
      showSettingsMessage(err.message, "err");
      e.target.checked = !e.target.checked;
    }
  });

  // UAT U19: validated client-side first, with the min/max the input already
  // carries plus a friendly message beside the field -- a bad value never
  // reaches the server, and #settings-message (easy to scroll past behind
  // the modal backdrop) never sees it either. A server 422 for this field
  // (a stale FINDPLUS_POLL_INTERVAL_MINUTES env var, a second tab) gets the
  // same friendly wording rather than config_keys.py's raw validator text.
  $("setting-poll-interval").addEventListener("input", renderPollRate);
  $("setting-retention-days").addEventListener("input", renderRetentionEffect);
  $("setting-poll-interval").addEventListener("change", async (e) => {
    if (!validatePollInterval(e.target.value)) return;
    try {
      await saveSettings({ "poll.interval_minutes": Number(e.target.value) });
    } catch (err) {
      if (err.status === 422) showPollIntervalError(true);
      else showSettingsMessage(err.message, "err");
    }
  });

  $("setting-retention-days").addEventListener("change", async (e) => {
    const days = e.target.value === "" ? null : Number(e.target.value);
    const bad = days !== null && !(Number.isInteger(days) && days >= MIN_RETENTION_DAYS);
    showRetentionError(bad);
    if (bad) return;
    try {
      await saveSettings({ "history.retention_days": days });
    } catch (err) {
      if (err.status === 422) showRetentionError(true);
      else showSettingsMessage(err.message, "err");
    }
  });

  // Reverted on failure: a stale number in a box is harmless, but a tick box
  // left in the post-click state would misstate what the server actually holds.
  $("setting-native-detail").addEventListener("change", async (e) => {
    try { await saveSettings({ "alerts.native_detail": e.target.checked }); }
    catch (err) { showSettingsMessage(err.message, "err"); e.target.checked = !e.target.checked; }
  });
}
