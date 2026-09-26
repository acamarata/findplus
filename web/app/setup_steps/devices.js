/*
 * Onboarding step 3 — Devices.
 *
 * Purpose    : Refresh the device list from every provider, let the user tick
 *              what to track and name or re-badge each one, then track the
 *              ticked set on Next (specs/onboarding.md § 4 row 3).
 * Inputs     : ctx.api / ctx.postJson / ctx.state, handed down by the Wizard.
 * Outputs    : POST /api/devices/refresh and GET /api/devices on enter; POST
 *              /api/devices/track on Next.
 * Constraints: Skip is a true no-op. It must never POST an empty track list,
 *              which would silently untrack whatever a previous run set up —
 *              only onNext writes.
 *              UAT6-N03 (BLOCKING, data loss): a failed `POST
 *              /api/devices/refresh` used to throw before the `GET
 *              /api/devices` that follows it ever ran, so a provider hiccup
 *              (or "Run setup again" with nothing signed in) rendered an
 *              empty list over real, already-tracked devices. Next then read
 *              zero ticked boxes, asked "Track nothing?", and OK posted
 *              `device_ids: []` -- untracking everything. refresh() now
 *              always runs the GET regardless of whether the POST succeeded,
 *              and onNext refuses to touch tracking at all when the list
 *              itself never loaded (`listFailed`), rather than falling
 *              through to the "nothing ticked" confirm meant for a user who
 *              deliberately unticked every row of a list that DID load.
 */
"use strict";

import { t } from "../i18n.js";
import { deviceRow } from "./_device_row.js";
import { confirmDialog } from "../components/confirm-dialog.js";
import { anyProviderSignedIn } from "../poll_status.js";

/** The live step's elements, replaced on every render. */
let els = null;
/** True when the last GET /api/devices itself failed: onNext must then be a
 * true no-op, the same guarantee Skip already gives (UAT6-N03). */
let listFailed = false;
/** True when the last successful GET /api/devices came back with zero rows:
 * UAT7-N10, there is nothing to tick and nothing to confirm, unlike a list
 * that loaded with every row deliberately unticked. */
let isEmptyList = false;

function renderRows(ctx, devices) {
  els.list.textContent = "";
  // UAT7-N10: an orphan "Track" column header sat above the empty state with
  // nothing underneath it to be a column header for.
  els.header.hidden = devices.length === 0;
  if (!devices.length) {
    const empty = document.createElement("p");
    empty.className = "fp-tab-hint";
    empty.textContent = t("setup.devices.empty");
    els.list.append(empty);
    return;
  }
  // UAT U15: on a fresh account nothing is tracked yet, so every row's own
  // is_tracked is false and every checkbox started unticked with nothing to
  // say so. Default every row to ticked in that one case; a re-entry that
  // already has some devices tracked keeps each row's own state instead.
  const noneTrackedYet = !devices.some((d) => d.is_tracked);
  const reload = () => refresh(ctx).catch(() => {});
  devices.forEach((device) =>
    els.list.append(deviceRow(ctx, device, reload, noneTrackedYet))
  );
}

/** UAT6-N07: the server's 409 for "no provider signed in" reads "Run
 * `findplus auth` first" -- a terminal command as the primary instruction.
 * Every other refresh failure (network blip, every provider unreachable) is
 * already a plain sentence from routes_devices.py, safe to show as-is. */
function refreshErrorText(err) {
  return err.status === 409 ? t("setup.devices.refresh_no_provider") : err.message;
}

/**
 * UAT6-N03: the Refresh button IS the visible "Retry" the finding asks for
 * -- it runs the exact same refresh() a failure needs retried, so a second
 * dedicated button beside the error line would just be a second way to do
 * the same thing. Split out of render() to keep that function under the
 * 50-line cap (PRI rule 7).
 */
function buildRefreshButton(ctx) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-secondary";
  btn.textContent = t("setup.devices.refresh");
  btn.addEventListener("click", () => {
    refresh(ctx).catch((err) => {
      els.error.textContent = refreshErrorText(err);
    });
  });
  return btn;
}

/**
 * Refresh from providers, then always read the known device list back.
 *
 * The two requests are independent on purpose (UAT6-N03): a refresh failure
 * must never hide devices Find+ already knows about, and a list-load failure
 * must never be read as "nothing to track" by onNext.
 */
async function refresh(ctx) {
  els.error.textContent = "";
  let refreshError = null;
  // UAT7-N10: refresh() used to POST /api/devices/refresh unconditionally,
  // which always 409s with no provider signed in and logged a console error
  // on every visit to this step on a bare install. `false` is a definite
  // answer (routes_devices.py's own 409 reason, without the doomed round
  // trip); `null` (locked, or the lookup itself failed) keeps the old
  // behaviour rather than guessing.
  if ((await anyProviderSignedIn()) === false) {
    refreshError = { status: 409, message: t("setup.devices.refresh_no_provider") };
  } else {
    try {
      await ctx.postJson("/api/devices/refresh");
    } catch (err) {
      refreshError = err;
    }
  }
  try {
    const body = await ctx.api("/api/devices");
    ctx.state.devices = body.devices || [];
    listFailed = false;
    isEmptyList = ctx.state.devices.length === 0;
    renderRows(ctx, ctx.state.devices);
    if (refreshError) els.error.textContent = refreshErrorText(refreshError);
  } catch (err) {
    listFailed = true;
    els.list.textContent = "";
    els.error.textContent = t("setup.devices.load_failed");
  }
}

export default {
  id: "devices",
  canSkip: true,
  render(container, ctx) {
    container.textContent = "";
    listFailed = false;
    isEmptyList = false;
    const heading = document.createElement("h2");
    heading.textContent = t("setup.devices.title");

    // UAT U15: the row checkboxes had no visible or accessible column
    // header; each row's own checkbox also carries an aria-label
    // ("Track {name}", _device_row.js) so a screen reader announces the
    // same word even without this text sitting directly above it.
    // UAT7-N10: hidden until refresh() knows whether there is anything to
    // be a column header for -- renderRows() shows it once devices.length
    // is known, rather than sitting over the empty state on first paint.
    const listHeader = document.createElement("p");
    listHeader.className = "fp-field-hint";
    listHeader.textContent = t("setup.devices.track");
    listHeader.hidden = true;

    const list = document.createElement("div");
    list.id = "fp-setup-devices-list";

    const error = document.createElement("p");
    error.className = "fp-dialog-error";
    error.id = "fp-setup-devices-error";
    // N45: a failed refresh went to ctx.showAlert -> #alert inside #app-shell,
    // hidden for the whole time the wizard is open (applock.js documents the
    // same trap). role="alert" announces this line the way a screen reader
    // announces applock's own field error.
    error.setAttribute("role", "alert");
    // Placed right after the error line (not before, as it used to sit) so a
    // failure's retry sits next to the words explaining why one is needed.
    const refreshBtn = buildRefreshButton(ctx);

    const note = document.createElement("p");
    note.className = "fp-wizard-footnote";
    // The dashboard will show these devices as stale when they are; say so
    // here, where the user is choosing which ones to watch.
    note.textContent = (ctx.state.config && ctx.state.config.notices.presence_stale) || "";

    els = { list, error, header: listHeader };
    container.append(heading, listHeader, list, error, refreshBtn, note);
  },
  async onEnter(ctx) {
    await refresh(ctx);
  },
  async onNext(ctx) {
    // UAT6-N03: the list never loaded -- there is nothing honest to post.
    // Behave like Skip: leave whatever tracking already existed alone.
    if (listFailed) return true;
    const ids = [...els.list.querySelectorAll("[data-track]")]
      .filter((el) => el.checked)
      .map((el) => el.dataset.deviceId);
    // UAT U15: Next used to POST an empty track list with no word about it,
    // silently leaving nothing tracked. A row exists to tick (the empty
    // step above already returns early) but none is ticked -- ask first.
    // UAT7-N10: a list that loaded with zero devices in it has nothing to
    // confirm -- that prompt is for a user who deliberately unticked a row
    // that DID exist, not a bare install with nothing to tick at all.
    if (!ids.length && !isEmptyList) {
      const confirmed = await confirmDialog({
        title: t("common.confirm"),
        body: t("setup.devices.confirm_none_tracked"),
      });
      if (!confirmed) return false;
    }
    await ctx.postJson("/api/devices/track", { device_ids: ids });
    // UAT U2: ctx.state.devices was still the pre-track snapshot from
    // onEnter's refresh(), so the Done step's count read is_tracked off
    // devices nobody had ticked yet. Re-fetch so every later step (Done,
    // and Groups if it never fetched its own copy) sees what was just set.
    const body = await ctx.api("/api/devices");
    ctx.state.devices = body.devices || [];
    return true;
  },
};
