/*
 * Settings dialog, app lock: set, change and remove the PIN.
 *
 * Purpose    : The three PIN actions and their field-level error lines. Split out
 *              of settings.js to stay under the 300-line file cap.
 * Inputs     : The Settings dialog's PIN inputs; settings.js's own
 *              showSettingsMessage() and loadSettings(), passed to
 *              wirePinActions() (the same shape settings_polling.js uses).
 * Outputs    : POST/DELETE /api/settings/pin; messages in the dialog.
 * Constraints: A rejection belongs beside the fields it is about, never in the
 *              dialog's top message line, which scrolls out of view (UAT3 N21,
 *              UAT #4). A PIN change re-locks this session at once.
 */
"use strict";

import { $ } from "./state.js";
import { api, postJson } from "./api.js";
import { showLock } from "./lock.js";
import { t } from "./i18n.js";
import { confirmDialog } from "./components/confirm-dialog.js";

/** security.py's MIN_PIN_LENGTH, kept in sync by hand, same discipline
 * honesty.py's sentences already require (specs/honesty.md). UAT4 N44. */
const MIN_PIN_LENGTH = 6;

/** The New PIN field's own error line (UAT3 N21, matching settings_polling.js's
 * showPollIntervalError): a mismatch or the server's 6-character minimum
 * render here, beside the field, rather than in #settings-message at the top
 * of the dialog. `message` null/empty clears it.
 *
 * GP-R5-5: a mismatch is about both fields, not just New PIN -- #confirm-pin
 * now carries the same aria-invalid state (and the same aria-describedby in
 * settings.html) so a screen reader on either field hears the rejection. */
export function showNewPinError(message) {
  const el = $("setting-new-pin-error");
  if (!el) return;
  el.textContent = message || "";
  el.classList.toggle("hidden", !message);
  $("new-pin").setAttribute("aria-invalid", String(!!message));
  $("confirm-pin").setAttribute("aria-invalid", String(!!message));
}

/**
 * The error line under the Change/Remove PIN fields (UAT #4). `field` names the
 * input the message is about ("current" or "new") so aria-invalid lands on it;
 * a null message clears the line and both marks.
 */
function showChangePinError(message, field) {
  const el = $("setting-change-pin-error");
  if (!el) return;
  el.textContent = message || "";
  el.classList.toggle("hidden", !message);
  $("current-pin").setAttribute("aria-invalid", String(!!message && field === "current"));
  $("change-pin").setAttribute("aria-invalid", String(!!message && field === "new"));
  if (message) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

/** Route a change/remove failure: a 403 is the current PIN (a 429 is the same
 * field, too many tries: say it beside the field), 400/422 the new one. */
function changeFailure(e, showSettingsMessage) {
  if (e.status === 403 || e.status === 429) showChangePinError(e.message, "current");
  else if (e.status === 400 || e.status === 422) showChangePinError(e.message, "new");
  else showSettingsMessage(e.message, "err");
}

/** Set a first PIN. Both fields must match before anything is sent. */
async function setPin({ showSettingsMessage, loadSettings }) {
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
async function changePin({ showSettingsMessage }) {
  const current = $("current-pin").value.trim();
  const next = $("change-pin").value.trim();
  showSettingsMessage(null); // UAT4 N40: clear a stale message before this attempt
  showChangePinError(null);
  if (!next) { showChangePinError(t("settings.enterNewPin"), "new"); return; }
  if (next.length < MIN_PIN_LENGTH) { showChangePinError(t("settings.pinTooShort"), "new"); return; }
  try {
    await postJson("/api/settings/pin", { new_pin: next, current_pin: current });
    $("current-pin").value = $("change-pin").value = "";
    showSettingsMessage(t("settings.pinChanged"), "warn");
    showLock();
  } catch (e) {
    changeFailure(e, showSettingsMessage);
  }
}

/**
 * Remove the PIN, which disables the lock entirely. The current PIN is checked
 * FIRST (POST /api/settings/pin/check, which changes nothing), so a wrong PIN is
 * reported beside the field before any "Remove the PIN?" question is asked
 * (UAT #4). The DELETE still checks it again: the server never trusts the dialog.
 */
async function removePin({ showSettingsMessage, loadSettings }) {
  const current = $("current-pin").value.trim();
  showSettingsMessage(null); // UAT4 N40: clear a stale message before this attempt
  showChangePinError(null);
  if (!current) { showChangePinError(t("settings.enterCurrentPin"), "current"); return; }
  try {
    await postJson("/api/settings/pin/check", { current_pin: current });
  } catch (e) {
    changeFailure(e, showSettingsMessage);
    return;
  }
  if (!(await confirmDialog({ title: t("common.remove"), body: t("settings.confirmRemovePin"), confirmLabel: t("common.remove"), danger: true }))) return;
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
    changeFailure(e, showSettingsMessage);
  }
}

/** Wire Set, Change and Remove PIN. `deps` are settings.js's own helpers. */
export function wirePinActions(deps) {
  $("btn-set-pin").addEventListener("click", () => setPin(deps));
  $("btn-change-pin").addEventListener("click", () => changePin(deps));
  $("btn-remove-pin").addEventListener("click", () => removePin(deps));
}
