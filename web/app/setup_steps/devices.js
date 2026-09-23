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
 */
"use strict";

import { t } from "../i18n.js";
import { deviceRow } from "./_device_row.js";

/** The live step's elements, replaced on every render. */
let els = null;

function renderRows(ctx, devices) {
  els.list.textContent = "";
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

async function refresh(ctx) {
  els.error.textContent = "";
  await ctx.postJson("/api/devices/refresh");
  const body = await ctx.api("/api/devices");
  ctx.state.devices = body.devices || [];
  renderRows(ctx, ctx.state.devices);
}

export default {
  id: "devices",
  canSkip: true,
  render(container, ctx) {
    container.textContent = "";
    const heading = document.createElement("h2");
    heading.textContent = t("setup.devices.title");

    // UAT U15: the row checkboxes had no visible or accessible column
    // header; each row's own checkbox also carries an aria-label
    // ("Track {name}", _device_row.js) so a screen reader announces the
    // same word even without this text sitting directly above it.
    const listHeader = document.createElement("p");
    listHeader.className = "fp-field-hint";
    listHeader.textContent = t("setup.devices.track");

    const list = document.createElement("div");
    list.id = "fp-setup-devices-list";

    const refreshBtn = document.createElement("button");
    refreshBtn.type = "button";
    refreshBtn.className = "btn btn-secondary";
    refreshBtn.textContent = t("setup.devices.refresh");
    refreshBtn.addEventListener("click", () => {
      refresh(ctx).catch((err) => {
        els.error.textContent = err.message;
      });
    });

    const error = document.createElement("p");
    error.className = "fp-dialog-error";
    error.id = "fp-setup-devices-error";
    // N45: a failed refresh went to ctx.showAlert -> #alert inside #app-shell,
    // hidden for the whole time the wizard is open (applock.js documents the
    // same trap). role="alert" announces this line the way a screen reader
    // announces applock's own field error.
    error.setAttribute("role", "alert");

    const note = document.createElement("p");
    note.className = "fp-wizard-footnote";
    // The dashboard will show these devices as stale when they are; say so
    // here, where the user is choosing which ones to watch.
    note.textContent = (ctx.state.config && ctx.state.config.notices.presence_stale) || "";

    els = { list, error };
    container.append(heading, listHeader, list, refreshBtn, error, note);
  },
  async onEnter(ctx) {
    await refresh(ctx);
  },
  async onNext(ctx) {
    const ids = [...els.list.querySelectorAll("[data-track]")]
      .filter((el) => el.checked)
      .map((el) => el.dataset.deviceId);
    // UAT U15: Next used to POST an empty track list with no word about it,
    // silently leaving nothing tracked. A row exists to tick (the empty
    // step above already returns early) but none is ticked -- ask first.
    if (!ids.length && !window.confirm(t("setup.devices.confirm_none_tracked"))) {
      return false;
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
