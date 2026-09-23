/*
 * Settings dialog: theme, idle timeout, app lock, and PIN management.
 *
 * Purpose    : Read/write the dashboard's own settings and the PIN that
 *              gates the app lock.
 * Constraints: A PIN change signs the browser back in immediately but every
 *              other open session is revoked server-side (see api-contract).
 */
"use strict";

import { $, state, applyTheme } from "./state.js";
import { api, postJson } from "./api.js";
import { showLock, startIdleTimer } from "./lock.js";
import { t } from "./i18n.js";
import { trapFocus } from "./components/dialog-trap.js";
import { renderPollingSection, wirePollingControls } from "./settings_polling.js";

/** security.py's MIN_PIN_LENGTH — kept in sync by hand, same discipline
 * honesty.py's sentences already require (specs/honesty.md). UAT4 N44. */
const MIN_PIN_LENGTH = 6;

/** The focus trap for #settings-modal while it is open, or null. */
let settingsTrap = null;

/**
 * Every error and confirmation this dialog produces (PIN set/changed/
 * removed, a rejected poll interval, a failed toggle…) renders here, inside
 * the open dialog, instead of the page banner behind it (UAT U19: "poll.
 * interval_minutes must be between 5 and 1440." was read in #alert, hidden
 * by the modal backdrop). `kind: "warn"` (a confirmation, not a failure)
 * reuses .modal-rate's tone; anything else is .fp-dialog-error's red.
 */
function showSettingsMessage(message, kind) {
  const el = $("settings-message");
  if (!el) return;
  el.textContent = message || "";
  el.className = kind === "warn" ? "modal-rate" : "fp-dialog-error";
  if (message) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

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

function renderLockSection() {
  const configured = state.settings && state.settings.pin_configured;
  $("lock-not-set").classList.toggle("hidden", !!configured);
  $("lock-is-set").classList.toggle("hidden", !configured);
  if (configured) {
    $("setting-lock-enabled").checked = state.settings.lock_enabled;
    $("setting-idle").value = String(state.settings.idle_minutes);
  }
  showNewPinError(null); // never a stale rejection from a previous open
}

/** The New PIN field's own error line (UAT3 N21, matching settings_polling.js's
 * showPollIntervalError): a mismatch or the server's 6-character minimum
 * render here, beside the field, rather than in #settings-message at the top
 * of the dialog. `message` null/empty clears it.
 *
 * GP-R5-5: a mismatch is about both fields, not just New PIN -- #confirm-pin
 * now carries the same aria-invalid state (and the same aria-describedby in
 * settings.html) so a screen reader on either field hears the rejection. */
function showNewPinError(message) {
  const el = $("setting-new-pin-error");
  if (!el) return;
  el.textContent = message || "";
  el.classList.toggle("hidden", !message);
  $("new-pin").setAttribute("aria-invalid", String(!!message));
  $("confirm-pin").setAttribute("aria-invalid", String(!!message));
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
  // data-loaded marks the end of the fills below, so anything that edits a
  // field (a test, a script) can wait for it: loadSettings() re-renders the
  // poll interval and clears its field error when it lands.
  delete $("settings-modal").dataset.loaded;
  $("settings-modal").classList.remove("hidden");
  settingsTrap = trapFocus($("settings-modal"), closeSettings);
  showSettingsMessage(null); // never a stale message from the previous open
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
    // U27: desktop-only, so a plain browser tab at :8647 never asks the OS to
    // start a process it cannot run there. window.__findplus_native is set
    // only by the Tauri window's init script (R-P2-13), same gate as the
    // native-detail row above.
    if (window.__findplus_native === true) {
      $("setting-group-desktop").hidden = false;
      const startAtLogin = await api("/api/settings/app.start_at_login");
      $("setting-start-at-login").checked = startAtLogin["app.start_at_login"];
    }
    // Re-read the sign-in status on every open (ruling R-P2-8): a sign-in
    // completed in a Chrome window or another tab is visible next time.
    // Dynamic, so settings.js keeps no static dependency on auth.js. Awaited
    // inside this try/catch: unawaited, a failed import or a mountAuthPanel
    // that threw rejected into nothing, leaving the panel blank with no
    // message anywhere (CR-C-E10 F2).
    const auth = await import("./auth.js");
    await auth.mountAuthPanel($("fp-settings-signin"));
  } catch (e) {
    showSettingsMessage(e.message, "err");
  } finally {
    $("settings-modal").dataset.loaded = "true";
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
  // UAT4 N40: a prior "PIN removed"/"PIN set" confirmation stayed at the top
  // of the dialog while this new attempt's own rejection rendered beside the
  // field, so the screen carried two contradictory messages at once. Any new
  // attempt clears it, same as showNewPinError(null) below clears the
  // field-level one.
  showSettingsMessage(null);
  showNewPinError(null); // clear a stale rejection before revalidating
  if (pin !== confirm) { showNewPinError(t("settings.pinsDoNotMatch")); return; }
  // UAT4 N44: the 6-character minimum (security.py's hash_pin()) used to
  // reach the server before failing, logging a 400. Checking it here first
  // is a courtesy that saves the round trip; the server still enforces it.
  if (pin.length < MIN_PIN_LENGTH) { showNewPinError(t("settings.pinTooShort")); return; }
  try {
    await postJson("/api/settings/pin", { new_pin: pin });
    $("new-pin").value = $("confirm-pin").value = "";
    await loadSettings();
    showSettingsMessage(t("settings.pinSet"), "warn");
  } catch (e) {
    // routes_settings.py's set_pin(): reject_padded_pin() answers 422, and the
    // 6-character minimum (security.py's hash_pin()) answers 400 -- both are
    // about what was typed into these two fields, not a dialog-level failure.
    if (e.status === 400 || e.status === 422) showNewPinError(e.message);
    else showSettingsMessage(e.message, "err");
  }
}

/** Change the PIN. The server revokes every other session, so this one re-locks. */
async function changePin() {
  const current = $("current-pin").value.trim();
  const next = $("change-pin").value.trim();
  showSettingsMessage(null); // UAT4 N40: clear a stale message before this attempt
  if (!next) { showSettingsMessage(t("settings.enterNewPin"), "warn"); return; }
  try {
    await postJson("/api/settings/pin", { new_pin: next, current_pin: current });
    $("current-pin").value = $("change-pin").value = "";
    showSettingsMessage(t("settings.pinChanged"), "warn");
    showLock();
  } catch (e) {
    showSettingsMessage(e.message, "err");
  }
}

/** Remove the PIN, which disables the lock entirely. Confirmed twice. */
async function removePin() {
  const current = $("current-pin").value.trim();
  showSettingsMessage(null); // UAT4 N40: clear a stale message before this attempt
  if (!current) { showSettingsMessage(t("settings.enterCurrentPin"), "warn"); return; }
  if (!window.confirm(t("settings.confirmRemovePin"))) return;
  try {
    await api("/api/settings/pin", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_pin: current }),
    });
    $("current-pin").value = "";
    await loadSettings();
    showSettingsMessage(t("settings.pinRemoved"), "warn");
  } catch (e) {
    showSettingsMessage(e.message, "err");
  }
}

/** Toggle the dialog open/closed, including the backdrop click. */
function wireModalToggle() {
  $("btn-settings").addEventListener("click", openSettings);
  $("btn-close-settings").addEventListener("click", closeSettings);
  $("settings-modal").addEventListener("click", (e) => {
    if (e.target.id === "settings-modal") closeSettings();
  });
}

/** Theme (instant-feedback) and the idle timeout / lock-enabled toggle. */
function wireThemeAndLockControls() {
  $("setting-theme").addEventListener("change", async (e) => {
    applyTheme(e.target.value);  // instant feedback
    try { await saveSettings({ theme: e.target.value }); }
    catch (err) { showSettingsMessage(err.message, "err"); }
  });

  $("setting-idle").addEventListener("change", async (e) => {
    try { await saveSettings({ idle_minutes: Number(e.target.value) }); }
    catch (err) { showSettingsMessage(err.message, "err"); }
  });

  $("setting-lock-enabled").addEventListener("change", async (e) => {
    try { await saveSettings({ lock_enabled: e.target.checked }); }
    catch (err) { showSettingsMessage(err.message, "err"); e.target.checked = !e.target.checked; }
  });
}

/** The rerun-setup nav link plus PIN set/change/remove buttons. */
function wirePinControls() {
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

/** Wire the settings dialog: toggle it open/closed, theme/idle/lock-enabled, PIN set/change/remove. */
export function wireSettingsControls() {
  wireModalToggle();
  wireThemeAndLockControls();
  wirePollingControls(saveSettings, showSettingsMessage);
  wirePinControls();
}
