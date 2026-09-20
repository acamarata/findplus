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
  return state.settings;
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

/** Open the Settings dialog, refreshing everything it displays. */
export async function openSettings() {
  try {
    await loadSettings();
    const req = await api("/api/lock/requirements");
    $("lock-caveat").textContent = req.caveat;
    const health = await api("/api/health");
    $("settings-about").textContent = t("settings.about", {
      version: health.version,
      schema: health.schema_revision,
      timezone: health.timezone,
      interval: state.config.poll_interval_minutes,
    });
    const startAtLogin = await api("/api/settings/app.start_at_login");
    $("setting-start-at-login").checked = startAtLogin["app.start_at_login"];
    $("settings-modal").classList.remove("hidden");
    settingsTrap = trapFocus($("settings-modal"), closeSettings);
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

  $("btn-set-pin").addEventListener("click", setPin);
  $("btn-change-pin").addEventListener("click", changePin);
  $("btn-remove-pin").addEventListener("click", removePin);
}
