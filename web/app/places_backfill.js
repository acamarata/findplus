/*
 * "3 places have no arrival alerts. Notify me": the backfill for places that
 * were saved before every new place got an arrival and departure alert.
 *
 * Purpose    : Offer, in one line above the places list, to add the default
 *              "anyone arrives or leaves" alert to every place that has none.
 *              The button first shows what it would add (a dry run), and only a
 *              second click writes anything.
 * Inputs     : POST /api/places/notify-defaults?dry_run=1, then without dry_run.
 * Outputs    : The banner inside #fp-places-backfill; a one-line result.
 * Constraints: createElement/textContent only. The preview says only new
 *              crossings are sent (never history) and carries the latency
 *              honesty sentence verbatim. A failed preview says so and keeps the
 *              banner (with Notify me retrying). purge() empties it on lock.
 */
"use strict";

import { postJson } from "./api.js";
import { plural, t } from "./i18n.js";
import { showAlert } from "./state.js";
import { confirmDialog } from "./components/confirm-dialog.js";
import { button } from "./components/button.js";

let host = null;
let onDone = null;

/** The Alerts tab's rules table was loaded before this rule existed. */
export function refreshRules() {
  import("./alerts_rules.js").then((m) => m.loadRules()).catch(() => {});
}

export function initBackfill(el, done) {
  host = el;
  onDone = done;
}

const dryRun = () => postJson("/api/places/notify-defaults?dry_run=1", {});

function channelsText(rule) {
  return rule.channels.map((c) => t(`alerts.channels.${c}`)).join(", ");
}

/** The preview text: one line per place, the switched-off warning if any, the latency sentence. */
export function previewBody(preview) {
  const lines = preview.rules.map((r) => t("places.backfill.line", { place: r.place_name, channels: channelsText(r) }));
  const off = preview.rules.some((r) => !r.enabled) ? [t("places.backfill.off")] : [];
  return [lines.join("\n"), ...off, t("people.notify.onlyNew"), t("honesty.alertsLatency")].join("\n\n");
}

async function apply(preview) {
  const confirmed = await confirmDialog({
    title: plural("places.backfill.title", preview.count, { n: preview.count }),
    body: previewBody(preview),
    confirmLabel: t("places.backfill.confirm"),
  });
  if (!confirmed) return;
  try {
    const done = await postJson("/api/places/notify-defaults", {});
    showAlert(plural("places.backfill.done", done.count, { n: done.count }), "info");
    refreshRules();
  } catch (err) {
    if (err.message !== "Locked") showAlert(t("places.backfill.failed", { message: err.message }), "err");
    return;
  }
  if (onDone) await onDone();
}

async function onNotifyMe(button) {
  button.disabled = true;
  try {
    const preview = await dryRun();
    if (preview.count) await apply(preview);
  } catch (err) {
    if (err.message !== "Locked") showAlert(t("places.backfill.previewFailed", { message: err.message }), "err");
  } finally {
    button.disabled = false;
  }
}

function draw(count) {
  const text = document.createElement("span");
  text.textContent = plural("places.backfill.text", count, { n: count });
  const notify = button({ label: t("places.backfill.button"), icon: "bell", variant: "secondary", size: "sm", id: "fp-places-backfill-btn" });
  notify.addEventListener("click", () => onNotifyMe(notify));
  host.replaceChildren(text, notify);
  host.hidden = false;
}

/** Look at how many places lack the alert; show or hide the banner. */
export async function refreshBackfill() {
  if (!host) return;
  try {
    const { count } = await dryRun();
    if (count) draw(count);
    else purgeBackfill();
  } catch (_) { /* offline or locked: leave the banner as it was */ }
}

export function purgeBackfill() {
  if (!host) return;
  host.replaceChildren();
  host.hidden = true;
}
