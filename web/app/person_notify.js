/*
 * "Notify me" on the Person page: one tap to hear when this person arrives or leaves.
 *
 * Purpose    : Turn on the default "anyone arrives or leaves" alert for every
 *              place that has none, which covers this person too. No name, no
 *              device to pick: Find+ chooses the channel, shows what it will
 *              add (including the delay sentence) and waits for one confirm.
 * Inputs     : The person, and `setStatus(text, kind)` for the page's status line.
 * Outputs    : POST /api/places/notify-defaults?dry_run=1, then without dry_run.
 * Constraints: Nothing is written before the confirm. With no places, or every
 *              place already covered, it says so instead of opening a form.
 */
"use strict";

import { api, postJson } from "./api.js";
import { plural, t } from "./i18n.js";
import { confirmDialog } from "./components/confirm-dialog.js";
import { previewBody } from "./places_backfill.js";

async function whyNothing(person) {
  const places = await api("/api/places");
  return places.length ? t("person.notify.already", { name: person.name }) : t("person.notify.noPlaces");
}

/** Preview, confirm, add. Never throws: every outcome is a sentence on the status line. */
export async function notifyMe(person, setStatus) {
  setStatus("", "");
  try {
    const preview = await postJson("/api/places/notify-defaults?dry_run=1", {});
    if (!preview.count) { setStatus(await whyNothing(person), "ok"); return; }
    const ok = await confirmDialog({
      title: t("person.notify.title", { name: person.name }),
      body: [t("person.notify.lead", { name: person.name }), previewBody(preview)].join("\n\n"),
      confirmLabel: t("places.backfill.confirm"),
    });
    if (!ok) return;
    const done = await postJson("/api/places/notify-defaults", {});
    setStatus(plural("person.notify.done", done.count, { n: done.count, name: person.name }), "ok");
    import("./places_backfill.js").then((m) => m.refreshRules()).catch(() => {});
  } catch (err) {
    if (err.message !== "Locked") setStatus(t("person.notify.failed", { message: err.message }), "err");
  }
}
