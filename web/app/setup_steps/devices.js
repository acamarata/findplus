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

import { plural, t } from "../i18n.js";
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
/** True when the last refresh found no provider signed in. */
let signedOut = false;

/** "2 of 3 selected", kept current as boxes are ticked (polite, not alerting). */
function updateCount() {
  const boxes = [...els.list.querySelectorAll("[data-track]")];
  els.count.hidden = boxes.length === 0;
  const n = boxes.filter((b) => b.checked).length;
  els.count.textContent = plural("setup.devices.selected", n, { n, total: boxes.length });
}

/** The empty list: one message when nothing is connected, one when it is. */
function emptyState(ctx) {
  const empty = document.createElement("p");
  empty.className = "fp-tab-hint";
  empty.textContent = t(signedOut ? "setup.devices.empty_signed_out" : "setup.devices.empty");
  els.list.append(empty);
  if (!signedOut) return;
  const back = document.createElement("button");
  back.type = "button";
  back.className = "btn btn-secondary";
  back.textContent = t("setup.devices.go_signin");
  back.addEventListener("click", () => ctx.goToStep("signin"));
  els.list.append(back);
}

function renderRows(ctx, devices) {
  els.list.textContent = "";
  els.list.removeAttribute("aria-busy");
  // UAT7-N10: an orphan "Track" column header sat above the empty state with
  // nothing underneath it to be a column header for.
  els.header.hidden = devices.length === 0;
  if (!devices.length) {
    emptyState(ctx);
    updateCount();
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
  updateCount();
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
async function refresh(ctx, quiet = false) {
  els.error.textContent = "";
  // Loading state: the list says what it is doing, and tells assistive tech.
  els.list.setAttribute("aria-busy", "true");
  if (!els.list.children.length) {
    const wait = document.createElement("p");
    wait.className = "fp-tab-hint";
    wait.textContent = t("setup.devices.loading");
    els.list.append(wait);
  }
  let refreshError = null;
  // UAT7-N10: refresh() used to POST /api/devices/refresh unconditionally,
  // which always 409s with no provider signed in and logged a console error
  // on every visit to this step on a bare install. `false` is a definite
  // answer (routes_devices.py's own 409 reason, without the doomed round
  // trip); `null` (locked, or the lookup itself failed) keeps the old
  // behaviour rather than guessing.
  signedOut = (await anyProviderSignedIn()) === false;
  if (signedOut) {
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
    // Arriving signed out with nothing listed is already explained by the empty state; only an
    // explicit Refresh click repeats the reason as an error.
    if (refreshError && !(quiet && signedOut && isEmptyList)) els.error.textContent = refreshErrorText(refreshError);
  } catch (err) {
    listFailed = true;
    els.list.textContent = "";
    els.list.removeAttribute("aria-busy");
    updateCount();
    els.error.textContent = t("setup.devices.load_failed");
  }
}

/** No-location explanation plus the stale-presence honesty sentence. */
function notes(ctx) {
  const wrap = document.createElement("div");
  const none = document.createElement("p");
  none.className = "fp-wizard-footnote";
  none.textContent = t("setup.devices.no_location");
  const stale = document.createElement("p");
  stale.className = "fp-wizard-footnote";
  // The dashboard will show these devices as stale when they are; say so
  // here, where the user is choosing which ones to watch.
  stale.textContent = (ctx.state.config && ctx.state.config.notices.presence_stale) || "";
  wrap.append(none, stale);
  return wrap;
}

export default {
  id: "devices",
  canSkip: true,
  render(container, ctx) {
    container.textContent = "";
    listFailed = false;
    isEmptyList = false;
    signedOut = false;
    const heading = document.createElement("h2");
    heading.textContent = t("setup.devices.title");
    const lead = document.createElement("p");
    lead.className = "fp-wizard-lead";
    lead.textContent = t("setup.devices.lead");

    // UAT U15 / UAT7-N10: the column header (also each checkbox's aria-label)
    // stays hidden until refresh() knows there is a list to head.
    const listHeader = document.createElement("p");
    listHeader.className = "fp-field-hint";
    listHeader.textContent = t("setup.devices.track");
    listHeader.hidden = true;

    const list = document.createElement("div");
    list.id = "fp-setup-devices-list";
    list.addEventListener("change", updateCount);

    const count = document.createElement("p");
    count.className = "fp-wizard-summary";
    count.id = "fp-setup-devices-count";
    count.setAttribute("aria-live", "polite");
    count.hidden = true;

    const error = document.createElement("p");
    error.className = "fp-dialog-error";
    error.id = "fp-setup-devices-error";
    // N45: #alert is hidden behind the wizard, so this line announces itself.
    error.setAttribute("role", "alert");
    els = { list, error, header: listHeader, count };
    container.append(
      heading, lead, listHeader, list, count, error, buildRefreshButton(ctx), notes(ctx)
    );
  },
  async onEnter(ctx) {
    await refresh(ctx, true);
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
