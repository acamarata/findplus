/*
 * Settings > Updates: the automatic switch, the status line, Check now, Update now.
 *
 * Purpose    : Let the owner see the installed version, what was found, turn
 *              automatic updates off, check by hand and install by hand.
 * Inputs     : GET /api/update/status, POST /api/update/check, the
 *              `updates.auto` key of /api/settings, the Tauri command apply_update.
 * Outputs    : #update-status-line text; the switch; two buttons.
 * Constraints: Update now shows only inside the Find+ app with an update staged.
 *              After Check now the line follows the check until it ends (at most
 *              two minutes). The honesty sentence is filled by notices.js.
 */
"use strict";

import { $ } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";
import { canInstall, installNow, readStatus, statusLine } from "./updates.js";

const FOLLOW_MS = 1500;
const FOLLOW_MAX = 80;

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function show(body) {
  $("update-status-line").textContent = statusLine(body);
  $("btn-update-now").hidden = !(canInstall() && body.staged_version);
  $("btn-update-check").disabled = !!body.checking;
}

/** Fill the section. Called each time Settings opens. */
export async function loadUpdateSettings(settings) {
  $("setting-updates-auto").checked = settings ? settings["updates.auto"] !== false : true;
  try {
    show(await readStatus());
  } catch (err) {
    if (err.message !== "Locked") $("update-status-line").textContent = t("updates.problem", { message: err.message });
  }
}

async function follow() {
  for (let i = 0; i < FOLLOW_MAX; i += 1) {
    const body = await readStatus();
    show(body);
    if (!body.checking) return;
    await pause(FOLLOW_MS);
  }
}

/** Wire the switch and the two buttons once. `save` is settings.js's saveSettings. */
export function wireUpdateSettings(save, say) {
  $("setting-updates-auto").addEventListener("change", async (e) => {
    try { await save({ "updates.auto": e.target.checked }); }
    catch (err) { say(err.message, "err"); e.target.checked = !e.target.checked; }
  });
  $("btn-update-check").addEventListener("click", async () => {
    try {
      show(await api("/api/update/check", { method: "POST" }));
      await follow();
    } catch (err) {
      if (err.message !== "Locked") say(t("updates.problem", { message: err.message }), "err");
    }
  });
  $("btn-update-now").addEventListener("click", async () => {
    $("btn-update-now").disabled = true;
    try {
      await installNow();
      $("update-status-line").textContent = t("updates.installing");
    } catch (err) {
      say(t("updates.installFailed", { message: String(err && err.message ? err.message : err) }), "err");
      $("btn-update-now").disabled = false;
    }
  });
}
