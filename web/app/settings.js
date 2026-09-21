/*
 * Settings dialog: theme, idle timeout, app lock, and PIN management.
 *
 * Purpose    : Read/write the dashboard's own settings and the PIN that
 *              gates the app lock.
 * Constraints: A PIN change signs the browser back in immediately but every
 *              other open session is revoked server-side (see api-contract).
 */
"use strict";

import { $, state, applyTheme, showAlert } from "./state.js";
import { api, postJson } from "./api.js";
import { showLock, startIdleTimer } from "./lock.js";
import { t } from "./i18n.js";
import { trapFocus } from "./components/dialog-trap.js";

/** The focus trap for #settings-modal while it is open, or null. */
let settingsTrap = null;

export async function loadSettings() {
  state.settings = await api("/api/settings");
  state.idleMinutes = state.settings.idle_minutes;
  applyTheme(state.settings.theme);
  $("setting-theme").value = state.settings.theme;
  $("btn-lock").classList.toggle("hidden", !state.settings.lock_active);
  renderLockSection();
  renderPollingSection();
  return state.settings;
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
function renderPollingSection() {
  $("setting-poll-interval").value = state.settings["poll.interval_minutes"];
  $("setting-retention-days").value = state.settings["history.retention_days"] ?? "";
  if (window.__findplus_native !== true) return;
  $("setting-native-detail-row").hidden = false;
  $("setting-native-detail-note").hidden = false;
  $("setting-native-detail").checked = state.settings["alerts.native_detail"];
  if (state.config && state.config.notices) {
    $("setting-native-detail-note").textContent = state.config.notices.native_generic;
  }
}

function renderLockSection() {
  const configured = state.settings && state.settings.pin_configured;
  $("lock-not-set").classList.toggle("hidden", !!configured);
  $("lock-is-set").classList.toggle("hidden", !configured);
  if (configured) {
    $("setting-lock-enabled").checked = state.settings.lock_enabled;
    $("setting-idle").value = String(state.settings.idle_minutes);
  }
}

export async function saveSettings(patch) {
  state.settings = await api("/api/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  state.idleMinutes = state.settings.idle_minutes;
  applyTheme(state.settings.theme);
  $("btn-lock").classList.toggle("hidden", !state.settings.lock_active);
  renderLockSection();
  startIdleTimer();
  return state.settings;
}

/**
 * Open the Settings dialog immediately, then fill in everything it shows.
 *
 * Unhiding and trapping focus happen before any await: a slow daemon or a
 * request that fails below must still leave the user a dialog they can see,
 * read and Escape out of, not a permanently hidden one. Before this, the
 * About line read state.config ahead of loadConfig() resolving and threw,
 * caught into the alert banner with #settings-modal never unhidden (CI run
 * 35546305331). state.config is now awaited explicitly, via main.js's own
 * loader (loadConfig() shares its in-flight request, so this is never a
 * second /api/config fetch) rather than assumed already loaded.
 */
export async function openSettings() {
  $("settings-modal").classList.remove("hidden");
  settingsTrap = trapFocus($("settings-modal"), closeSettings);
  try {
    await loadSettings();
    const req = await api("/api/lock/requirements");
    $("lock-caveat").textContent = req.caveat;
    if (!state.config) {
      const main = await import("./main.js");
      await main.loadConfig();
    }
    const health = await api("/api/health");
    $("settings-about").textContent = t("settings.about", {
      version: health.version,
      schema: health.schema_revision,
      timezone: health.timezone,
      interval: state.config.poll_interval_minutes,
    });
    const startAtLogin = await api("/api/settings/app.start_at_login");
    $("setting-start-at-login").checked = startAtLogin["app.start_at_login"];
    // Re-read the sign-in status on every open (ruling R-P2-8): a sign-in
    // completed in a Chrome window or another tab is visible next time.
    // Dynamic, so settings.js keeps no static dependency on auth.js. Awaited
    // inside this try/catch: unawaited, a failed import or a mountAuthPanel
    // that threw rejected into nothing, leaving the panel blank with no
    // message anywhere (CR-C-E10 F2).
    const auth = await import("./auth.js");
    await auth.mountAuthPanel($("fp-settings-signin"));
  } catch (e) {
    showAlert(e.message, "err");
  }
}

/** Hide the dialog and hand focus back to whatever opened it. */
export function closeSettings() {
  $("settings-modal").classList.add("hidden");
  if (settingsTrap) {
    settingsTrap.release();
    settingsTrap = null;
  }
}

/** Set a first PIN. Both fields must match before anything is sent. */
async function setPin() {
  const pin = $("new-pin").value.trim();
  const confirm = $("confirm-pin").value.trim();
  if (pin !== confirm) { showAlert(t("settings.pinsDoNotMatch"), "warn"); return; }
  try {
    await postJson("/api/settings/pin", { new_pin: pin });
    $("new-pin").value = $("confirm-pin").value = "";
    await loadSettings();
    showAlert(t("settings.pinSet"), "warn");
  } catch (e) {
    showAlert(e.message, "err");
  }
}

/** Change the PIN. The server revokes every other session, so this one re-locks. */
async function changePin() {
  const current = $("current-pin").value.trim();
  const next = $("change-pin").value.trim();
  if (!next) { showAlert(t("settings.enterNewPin"), "warn"); return; }
  try {
    await postJson("/api/settings/pin", { new_pin: next, current_pin: current });
    $("current-pin").value = $("change-pin").value = "";
    showAlert(t("settings.pinChanged"), "warn");
    showLock();
  } catch (e) {
    showAlert(e.message, "err");
  }
}

/** Remove the PIN, which disables the lock entirely. Confirmed twice. */
async function removePin() {
  const current = $("current-pin").value.trim();
  if (!current) { showAlert(t("settings.enterCurrentPin"), "warn"); return; }
  if (!window.confirm(t("settings.confirmRemovePin"))) return;
  try {
    await api("/api/settings/pin", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_pin: current }),
    });
    $("current-pin").value = "";
    await loadSettings();
    showAlert(t("settings.pinRemoved"), "warn");
  } catch (e) {
    showAlert(e.message, "err");
  }
}

/** Wire the settings dialog: toggle it open/closed, theme/idle/lock-enabled, PIN set/change/remove. */
export function wireSettingsControls() {
  $("btn-settings").addEventListener("click", openSettings);
  $("btn-close-settings").addEventListener("click", closeSettings);
  $("settings-modal").addEventListener("click", (e) => {
    if (e.target.id === "settings-modal") closeSettings();
  });

  $("setting-theme").addEventListener("change", async (e) => {
    applyTheme(e.target.value);  // instant feedback
    try { await saveSettings({ theme: e.target.value }); }
    catch (err) { showAlert(err.message, "err"); }
  });

  $("setting-idle").addEventListener("change", async (e) => {
    try { await saveSettings({ idle_minutes: Number(e.target.value) }); }
    catch (err) { showAlert(err.message, "err"); }
  });

  $("setting-lock-enabled").addEventListener("change", async (e) => {
    try { await saveSettings({ lock_enabled: e.target.checked }); }
    catch (err) { showAlert(err.message, "err"); e.target.checked = !e.target.checked; }
  });

  $("setting-start-at-login").addEventListener("change", async (e) => {
    try {
      await postJson("/api/settings/app.start_at_login", { value: e.target.checked });
    } catch (err) {
      showAlert(err.message, "err");
      e.target.checked = !e.target.checked;
    }
  });

  $("setting-poll-interval").addEventListener("change", async (e) => {
    try { await saveSettings({ "poll.interval_minutes": Number(e.target.value) }); }
    catch (err) { showAlert(err.message, "err"); }
  });

  $("setting-retention-days").addEventListener("change", async (e) => {
    try {
      await saveSettings({
        "history.retention_days": e.target.value === "" ? null : Number(e.target.value),
      });
    } catch (err) { showAlert(err.message, "err"); }
  });

  // Reverted on failure: a stale number in a box is harmless, but a tick box
  // left in the post-click state would misstate what the server actually holds.
  $("setting-native-detail").addEventListener("change", async (e) => {
    try { await saveSettings({ "alerts.native_detail": e.target.checked }); }
    catch (err) { showAlert(err.message, "err"); e.target.checked = !e.target.checked; }
  });

  // Navigation only. Re-running the wizard and abandoning it leaves
  // onboarding.completed_at exactly as it was; only Done ever writes it.
  $("btn-rerun-setup").addEventListener("click", () => {
    closeSettings();
    window.location.hash = "#/setup";
  });

  $("btn-set-pin").addEventListener("click", setPin);
  $("btn-change-pin").addEventListener("click", changePin);
  $("btn-remove-pin").addEventListener("click", removePin);
}
