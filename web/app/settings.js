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
    method: "PUT",
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
    $("settings-about").textContent =
      `findplus ${health.version} · schema ${health.schema_revision} · ` +
      `timezone ${health.timezone} · polling every ${state.config.poll_interval_minutes} min`;
    $("settings-modal").classList.remove("hidden");
  } catch (e) {
    showAlert(e.message, "err");
  }
}

/** Wire the settings dialog: toggle it open/closed, theme/idle/lock-enabled, PIN set/change/remove. */
export function wireSettingsControls() {
  $("btn-settings").addEventListener("click", openSettings);
  $("btn-close-settings").addEventListener("click", () => $("settings-modal").classList.add("hidden"));
  $("settings-modal").addEventListener("click", (e) => {
    if (e.target.id === "settings-modal") $("settings-modal").classList.add("hidden");
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

  $("btn-set-pin").addEventListener("click", async () => {
    const pin = $("new-pin").value;
    const confirm = $("confirm-pin").value;
    if (pin !== confirm) { showAlert("The two PINs do not match.", "warn"); return; }
    try {
      await postJson("/api/settings/pin", { new_pin: pin });
      $("new-pin").value = $("confirm-pin").value = "";
      await loadSettings();
      showAlert("PIN set. The app will lock when idle and whenever the service restarts.", "warn");
    } catch (e) {
      showAlert(e.message, "err");
    }
  });

  $("btn-change-pin").addEventListener("click", async () => {
    const current = $("current-pin").value;
    const next = $("change-pin").value;
    if (!next) { showAlert("Enter the new PIN.", "warn"); return; }
    try {
      await postJson("/api/settings/pin", { new_pin: next, current_pin: current });
      $("current-pin").value = $("change-pin").value = "";
      showAlert("PIN changed. All existing sessions were signed out.", "warn");
      showLock();
    } catch (e) {
      showAlert(e.message, "err");
    }
  });

  $("btn-remove-pin").addEventListener("click", async () => {
    const current = $("current-pin").value;
    if (!current) { showAlert("Enter the current PIN to remove it.", "warn"); return; }
    if (!window.confirm("Remove the PIN and disable the app lock?")) return;
    try {
      const res = await fetch(`/api/settings/pin?current_pin=${encodeURIComponent(current)}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      $("current-pin").value = "";
      await loadSettings();
      showAlert("PIN removed. The app no longer locks.", "warn");
    } catch (e) {
      showAlert(e.message, "err");
    }
  });
}
