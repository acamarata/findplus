/*
 * Updates: read where the update stands, word it, and ask the app to install.
 *
 * Purpose    : Shared by the dashboard corner button (update_banner.js) and the
 *              Settings > Updates section (settings_updates.js).
 * Inputs     : GET /api/update/status; window.__TAURI__ inside the Find+ app.
 * Outputs    : readStatus(), statusLine(body), canInstall(), installNow().
 * Constraints: Installing is the desktop shell's job (Tauri command
 *              apply_update): it backs up, quits, swaps the app and restarts.
 *              A plain browser tab can only say an update exists.
 *              Every string comes from the catalog; no inline English.
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";

/** True inside the Find+ desktop app, which alone can install an update. */
export function canInstall() {
  return window.__findplus_native === true && !!(window.__TAURI__ && window.__TAURI__.core);
}

export function readStatus() {
  return api("/api/update/status");
}

/** Ask the desktop shell to install the staged update now. Resolves before the restart. */
export function installNow() {
  return window.__TAURI__.core.invoke("apply_update");
}

const when = (iso) =>
  new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** The version a person can act on: staged first, else the newest release found. */
export function offeredVersion(body) {
  if (body.staged_version) return body.staged_version;
  return body.available ? body.latest_version : null;
}

function headline(body) {
  if (body.checking) return t("updates.checking");
  if (body.last_attempt_failed) return t("updates.failed", { version: body.current_version });
  if (body.staged_version) {
    const key = body.staged_source === "dev" ? "updates.readyDev" : "updates.ready";
    return t(key, { version: body.staged_version });
  }
  if (body.available) return t("updates.available", { version: body.latest_version });
  return body.checked_at && !body.error ? t("updates.upToDate") : "";
}

/** One status paragraph for a GET /api/update/status body. */
export function statusLine(body) {
  const parts = [t("updates.installed", { version: body.current_version }), headline(body)];
  if (body.error && !body.checking) parts.push(t("updates.problem", { message: body.error }));
  if (!body.checking) {
    parts.push(body.checked_at ? t("updates.checkedAt", { when: when(body.checked_at) }) : t("updates.neverChecked"));
  }
  if (body.backup_at) parts.push(t("updates.backupAt", { when: when(body.backup_at) }));
  return parts.filter(Boolean).join(" ");
}
