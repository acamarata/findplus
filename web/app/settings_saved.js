/*
 * Settings dialog: the "Saved." status line and the settings backup download.
 *
 * Purpose    : Every Settings control saves the moment it changes, so each save
 *              confirms itself in one polite status line near the top of the
 *              dialog (#settings-saved) instead of silently succeeding. The
 *              backup button downloads the public settings as a JSON file.
 * Inputs     : #settings-saved, #btn-export-settings; GET /api/settings.
 * Outputs    : markSaved() for every successful save; wireBackup(showMessage).
 * Constraints: GET /api/settings is the public payload only (no PIN hash or
 *              salt, no tokens); the file is built in the browser, never sent
 *              anywhere. The line clears itself after a few seconds.
 */
"use strict";

import { $ } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";

const SHOW_MS = 3500;
let clearTimer = null;

/** Say "Saved." in the dialog for a moment. Safe to call when the dialog is closed. */
export function markSaved() {
  const el = $("settings-saved");
  if (!el) return;
  el.textContent = t("settings.saved");
  if (clearTimer) clearTimeout(clearTimer);
  clearTimer = setTimeout(() => { el.textContent = ""; clearTimer = null; }, SHOW_MS);
}

/** Forget any "Saved." line (a new open of the dialog starts clean). */
export function clearSaved() {
  const el = $("settings-saved");
  if (clearTimer) clearTimeout(clearTimer);
  clearTimer = null;
  if (el) el.textContent = "";
}

/** A file name that sorts by date: findplus-settings-2026-10-01.json. */
function backupName() {
  return `findplus-settings-${new Date().toISOString().slice(0, 10)}.json`;
}

/** Download the public settings as JSON. */
async function downloadSettings(showMessage) {
  try {
    const body = await api("/api/settings");
    const blob = new Blob([JSON.stringify(body, null, 2) + "\n"], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = backupName();
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    showMessage(t("settings.backupFailed", { message: err.message }), "err");
  }
}

/** Wire the Download settings button. */
export function wireBackup(showMessage) {
  $("btn-export-settings").addEventListener("click", () => downloadSettings(showMessage));
}
