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
  const reload = () => refresh(ctx).catch(() => {});
  devices.forEach((device) => els.list.append(deviceRow(ctx, device, reload)));
}

async function refresh(ctx) {
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

    const list = document.createElement("div");
    list.id = "fp-setup-devices-list";

    const refreshBtn = document.createElement("button");
    refreshBtn.type = "button";
    refreshBtn.className = "btn btn-secondary";
    refreshBtn.textContent = t("setup.devices.refresh");
    refreshBtn.addEventListener("click", () => {
      refresh(ctx).catch((err) => ctx.showAlert(err.message, "err"));
    });

    const note = document.createElement("p");
    note.className = "fp-wizard-footnote";
    // The dashboard will show these devices as stale when they are; say so
    // here, where the user is choosing which ones to watch.
    note.textContent = (ctx.state.config && ctx.state.config.notices.presence_stale) || "";

    els = { list };
    container.append(heading, list, refreshBtn, note);
  },
  async onEnter(ctx) {
    await refresh(ctx);
  },
  async onNext(ctx) {
    const ids = [...els.list.querySelectorAll("[data-track]")]
      .filter((el) => el.checked)
      .map((el) => el.dataset.deviceId);
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
