/*
 * Device list, the device-manager modal, and manual poll wiring.
 *
 * Purpose    : List Find Hub devices, choose which are tracked, and show the
 *              resulting request-rate estimate.
 * Constraints: `poll-now` is the only control wired here that queries Google.
 */
"use strict";

import { $, state, colorFor, showAlert, esc } from "./state.js";
import { api, postJson } from "./api.js";
import { reload, applyHashRoute } from "./main.js";
import { loadPresence } from "./places.js";
import { t } from "./i18n.js";

/** "google-find-hub" → "Find Hub"; "apple-find-my" → the honesty-spec short form. */
export function providerLabel(p) {
  if (p === "google-find-hub") return t("devices.providerGoogleFindHub");
  if (p === "apple-find-my") return t("devices.providerAppleFindMy");
  return p || t("devices.providerUnknown");
}

/** The "All tracked devices" row, built as a node so no translated string is parsed as markup. */
function allTrackedOption() {
  const opt = document.createElement("option");
  opt.value = "";
  opt.textContent = t("devices.allTracked");
  return opt;
}

export function renderDeviceFilter() {
  const select = $("device-filter");
  const current = state.deviceFilter;
  while (select.firstChild) select.removeChild(select.firstChild);
  select.appendChild(allTrackedOption());
  state.devices
    .filter((d) => d.is_tracked || d.observation_count > 0)
    .forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.device_id;
      opt.textContent =
        d.name + " (" + providerLabel(d.provider) + ")" + (d.is_tracked ? "" : t("devices.notPolledSuffix"));
      select.appendChild(opt);
    });
  select.value = current;
  if (select.value !== current) { state.deviceFilter = ""; select.value = ""; }
}

export function renderDeviceModal() {
  const host = $("device-list");
  host.innerHTML = "";
  if (!state.devices.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = t("devices.emptyState");
    host.appendChild(empty);
  }
  state.devices.forEach((d) => {
    const row = document.createElement("label");
    row.className = "device-row";
    row.innerHTML =
      `<input type="checkbox" value="${esc(d.device_id)}" ${d.is_tracked ? "checked" : ""}>` +
      `<span><span class="d-name">${esc(d.name)}</span><br>` +
      `<span class="d-id">${esc(d.device_id)}</span></span>` +
      `<span class="d-obs">${esc(t("devices.obsCount", { n: Number(d.observation_count) || 0 }))}</span>`;
    row.dataset.deviceId = d.device_id;
    const badge = document.createElement("span");
    badge.className = "fp-provider-badge fp-provider-badge--" + (d.provider || "unknown");
    badge.textContent = providerLabel(d.provider);
    row.appendChild(badge);
    row.querySelector("input").addEventListener("change", updateModalRate);
    host.appendChild(row);
  });
  // The rows are the point of this dialog. Everything after them is a
  // decoration -- the request-rate line and the presence chips -- and a
  // failure in either used to propagate out of openDevices() before it
  // removed `hidden`, so the rows sat in the DOM invisible (CI-2, CI run
  // 35530635344: the row resolved but was hidden through 61 retries).
  try {
    updateModalRate();
  } catch (err) {
    console.error("updateModalRate failed", err);
  }
  try {
    loadPresence();
  } catch (err) {
    console.error("loadPresence failed", err);
  }
}

export function updateModalRate() {
  const checked = document.querySelectorAll("#device-list input:checked").length;
  const interval = (state.config && state.config.poll_interval_minutes) || 5;
  const rate = Math.round((checked * 60) / interval);
  const w = providerWording();
  $("device-rate").textContent = checked
    ? t("devices.rateTracked", { count: checked, rate, requests: w.requests, interval })
    : t("devices.rateNothing", { requests: w.requests });
}

export async function loadDevices() {
  const body = await api("/api/devices");
  state.devices = body.devices;
  state.devices.forEach((d) => colorFor(d.device_id));
  renderDeviceFilter();
  syncProviderNotice();
  syncProviderChrome();
  return body;
}

/**
 * Render each provider's footer sentence only when that provider is tracked.
 *
 * The footer used to render the Find Hub sentence unconditionally, so someone
 * tracking only AirTags read that their tags report "through Google Find Hub
 * network" (E1 honesty pass F1). Gating the Apple sentence alone left that
 * false sentence on screen, so both are device-derived now. Both come verbatim
 * from /api/config.notices, so honesty.py stays the single source.
 *
 * With no devices at all neither sentence renders: there is no history on
 * screen for either one to describe.
 */
/**
 * What to call the tracking side, derived from the tracked device set.
 *
 * Round 1 gated the footer honesty sentence and left the chrome around it
 * speaking only Google: an Apple-only user still read "Last observed by Find
 * Hub", "Devices on this Google account" and "about N Google requests per
 * hour" (E1 honesty round 2 F3). `network` names the tracking network,
 * `account` the account the devices hang off, `requests` the thing being
 * queried. A mixed or unknown set falls back to neutral wording rather than
 * picking a side.
 */
export function providerWording() {
  const providers = new Set(
    (state.devices || []).filter((d) => d.is_tracked !== false).map((d) => d.provider)
  );
  const apple = providers.has("apple-find-my");
  const other = [...providers].some((p) => p && p !== "apple-find-my");
  // The provider names are trademarks and stay as they are; only the neutral
  // fallback wording is prose a translator owns.
  if (apple && !other) return { network: "Find My", account: "Apple", requests: "Apple" };
  if (other && !apple) return { network: "Find Hub", account: "Google", requests: "Google" };
  return {
    network: t("devices.wordingProviders"),
    account: t("devices.wordingTracking"),
    requests: t("devices.wordingProviders"),
  };
}

/**
 * Rewrite the provider-named chrome for the current device set.
 *
 * These strings live in the markup because they are there before any device
 * list is loaded; this is the one place that keeps them true afterwards.
 */
export function syncProviderChrome() {
  const w = providerWording();
  const poll = $("btn-poll");
  if (poll) poll.title = t("devices.pollTitleFor", { requests: w.requests });
  const observed = $("card-observed-label");
  if (observed) observed.textContent = t("devices.cardObservedFor", { network: w.network });
  const heading = $("device-modal-title");
  if (heading) heading.textContent = t("devices.titleForAccount", { account: w.account });
  const note = $("device-modal-note");
  if (note) note.textContent = t("devices.noteForRequests", { requests: w.requests });
}

export function syncProviderNotice() {
  const notices = state.config?.notices;
  setNotice($("apple-notice"), (d) => d.provider === "apple-find-my", notices?.apple);
  setNotice($("findhub-notice"), (d) => d.provider !== "apple-find-my", notices?.find_hub);
}

/** Show `text` on `el` when at least one tracked device matches `pred`. */
function setNotice(el, pred, text) {
  if (!el) return;
  const show = Boolean(text) && state.devices.some(pred);
  el.textContent = show ? text : "";
  el.hidden = !show;
}

/**
 * Open the Devices dialog.
 *
 * The dialog is revealed whatever happened while filling it: a failed device
 * fetch, a missing chrome element or a presence request that never landed must
 * not leave the user clicking a button that does nothing, and must not leave
 * the rows rendered but invisible.
 */
export async function openDevices() {
  try {
    await loadDevices();
    renderDeviceModal();
  } catch (err) {
    showAlert(t("devices.loadFailed", { message: err.message }), "err");
  } finally {
    $("device-modal").classList.remove("hidden");
  }
}

/** Wire the device filter, device-manager modal, and manual poll button. */
export function wireDeviceControls() {
  $("device-filter").addEventListener("change", async (e) => {
    state.deviceFilter = e.target.value;
    localStorage.setItem("findplus.deviceFilter", state.deviceFilter);
    await reload();
  });

  $("btn-poll").addEventListener("click", async () => {
    const btn = $("btn-poll");
    btn.disabled = true;
    btn.textContent = t("devices.pollingLabel");
    try {
      const r = await postJson("/api/poll-now");
      const lines = r.results.map(
        (x) =>
          t("devices.pollResultLine", { device: x.device_name, status: x.status }) +
          (x.observations_new ? t("devices.pollResultNew", { n: x.observations_new }) : "")
      );
      showAlert(
        t("devices.polled", {
          devices: r.devices_polled,
          observations: r.observations_new,
          lines: lines.join(" · "),
        }),
        "warn"
      );
      await reload();
    } catch (err) {
      showAlert(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = t("common.btnPoll");
    }
  });

  // --- device manager ---
  $("btn-devices").addEventListener("click", openDevices);
  window.addEventListener("hashchange", applyHashRoute);
  $("btn-close-devices").addEventListener("click", () => $("device-modal").classList.add("hidden"));
  $("device-modal").addEventListener("click", (e) => {
    if (e.target.id === "device-modal") $("device-modal").classList.add("hidden");
  });

  $("btn-track-all").addEventListener("click", () => {
    document.querySelectorAll("#device-list input").forEach((i) => { i.checked = true; });
    updateModalRate();
  });
  $("btn-track-none").addEventListener("click", () => {
    document.querySelectorAll("#device-list input").forEach((i) => { i.checked = false; });
    updateModalRate();
  });

  $("btn-refresh-devices").addEventListener("click", async () => {
    const btn = $("btn-refresh-devices");
    btn.disabled = true;
    btn.textContent = t("devices.askingProvidersLabel");
    try {
      const r = await postJson("/api/devices/refresh");
      await loadDevices();
      renderDeviceModal();
      // Name the providers that answered. "on the account" was singular and
      // Google-shaped while the button said "your providers" (round 2 F4);
      // a partial failure must say which one was skipped, not stay silent.
      const asked = (r.providers || []).length;
      const failed = Object.keys(r.errors || {});
      let msg = t("devices.refreshFound", { found: r.found, providers: asked });
      if (failed.length) msg += t("devices.refreshUnreachable", { names: failed.join(", ") });
      showAlert(msg, "warn");
    } catch (err) {
      showAlert(t("devices.refreshFailed", { message: err.message }), "err");
    } finally {
      btn.disabled = false;
      btn.textContent = t("devices.refreshProvidersLabel");
    }
  });

  $("btn-save-devices").addEventListener("click", async () => {
    const ids = [...document.querySelectorAll("#device-list input:checked")].map((i) => i.value);
    try {
      const r = await postJson("/api/devices/track", { device_ids: ids });
      $("device-modal").classList.add("hidden");
      await loadDevices();
      showAlert(
        r.tracked_count
          ? t("devices.trackedResult", {
              count: r.tracked_count,
              rate: r.requests_per_hour,
              requests: providerWording().requests,
            })
          : t("devices.trackedNone", { requests: providerWording().requests }),
        "warn"
      );
      await reload();
    } catch (err) {
      showAlert(err.message, "err");
    }
  });
}
