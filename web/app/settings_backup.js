/*
 * Settings: the backup status line and "Back up now".
 *
 * Purpose    : Say when the database was last backed up and let the owner take one
 *              now. Automatic backups run daily; this is for before a risky change.
 * Inputs     : GET /api/settings/backup, POST /api/settings/backup/now.
 * Outputs    : A block for the people section; `say(text, kind)` reports results.
 * Constraints: createElement/textContent only. A failed read says so instead of
 *              claiming there is no backup. The note says what a backup leaves out.
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

const when = (iso) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** The one-line status for a GET /api/settings/backup body. */
export function backupLine(body) {
  if (!body.last_backup_at) return t("person.settings.backupNone");
  const kind = t(`person.settings.backupKind.${body.last_kind || "auto"}`);
  return t("person.settings.backupLast", { when: when(body.last_backup_at), kind, count: body.count });
}

async function refresh(line) {
  try {
    line.textContent = backupLine(await api("/api/settings/backup"));
  } catch (err) {
    if (err.message !== "Locked") line.textContent = t("person.settings.backupLoadFailed", { message: err.message });
  }
}

/** The backup block. `say` is the section's status writer. */
export async function backupSection(say) {
  const box = el("div", "person-backup");
  const line = el("p", "", "");
  line.id = "person-backup-line";
  const button = el("button", "btn btn-tiny", t("person.settings.backupNow"));
  button.type = "button";
  button.id = "person-backup-now";
  button.addEventListener("click", async () => {
    button.disabled = true;
    say("", "");
    try {
      line.textContent = backupLine(await api("/api/settings/backup/now", { method: "POST" }));
      say(t("person.settings.backupDone"), "ok");
    } catch (err) {
      if (err.message !== "Locked") say(t("person.settings.backupFailed", { message: err.message }), "err");
    } finally {
      button.disabled = false;
    }
  });
  await refresh(line);
  box.append(el("h4", "ps-sub", t("person.settings.backupTitle")), line, button, el("p", "modal-note", t("person.settings.backupNote")));
  return box;
}
