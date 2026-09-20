/*
 * Device list, the device-manager modal, and manual poll wiring.
 *
 * Purpose    : List Find Hub devices, choose which are tracked, and show the
 *              resulting request-rate estimate.
 * Constraints: `poll-now` is the only control wired here that queries Google.
 */
"use strict";

import { $, state, colorFor, showAlert } from "./state.js";
import { api, postJson } from "./api.js";
import { reload, applyHashRoute } from "./main.js";
import { loadPresence } from "./places.js";

/** "google-find-hub" → "Find Hub"; "apple-find-my" → the honesty-spec short form. */
export function providerLabel(p) {
  if (p === "google-find-hub") return "Find Hub";
  if (p === "apple-find-my") return "Apple Find My (keys you hold)";
  return p || "Unknown";
}

export function renderDeviceFilter() {
  const select = $("device-filter");
  const current = state.deviceFilter;
  select.innerHTML = `<option value="">All tracked devices</option>`;
  state.devices
    .filter((d) => d.is_tracked || d.observation_count > 0)
    .forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d.device_id;
      opt.textContent = d.name + " (" + providerLabel(d.provider) + ")" + (d.is_tracked ? "" : " (not polled)");
      select.appendChild(opt);
    });
  select.value = current;
  if (select.value !== current) { state.deviceFilter = ""; select.value = ""; }
}

export function renderDeviceModal() {
  const host = $("device-list");
  host.innerHTML = "";
  if (!state.devices.length) {
    host.innerHTML = `<div class="empty">No devices known yet. Use "Refresh from your providers".</div>`;
  }
  state.devices.forEach((d) => {
    const row = document.createElement("label");
    row.className = "device-row";
    row.innerHTML =
      `<input type="checkbox" value="${d.device_id}" ${d.is_tracked ? "checked" : ""}>` +
      `<span><span class="d-name">${d.name}</span><br><span class="d-id">${d.device_id}</span></span>` +
      `<span class="d-obs">${d.observation_count} obs</span>`;
    row.dataset.deviceId = d.device_id;
    const badge = document.createElement("span");
    badge.className = "fp-provider-badge fp-provider-badge--" + (d.provider || "unknown");
    badge.textContent = providerLabel(d.provider);
    row.appendChild(badge);
    row.querySelector("input").addEventListener("change", updateModalRate);
    host.appendChild(row);
  });
  updateModalRate();
  loadPresence();
}

export function updateModalRate() {
  const checked = document.querySelectorAll("#device-list input:checked").length;
  const interval = (state.config && state.config.poll_interval_minutes) || 5;
  const rate = Math.round((checked * 60) / interval);
  const w = providerWording();
  $("device-rate").textContent = checked
    ? `${checked} device(s) tracked → about ${rate} ${w.requests} requests per hour, polled sequentially every ${interval} min.`
    : `Nothing tracked — the poller will not query ${w.requests} at all.`;
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
    state.devices.filter((d) => d.is_tracked !== false).map((d) => d.provider)
  );
  const apple = providers.has("apple-find-my");
  const other = [...providers].some((p) => p && p !== "apple-find-my");
  if (apple && !other) return { network: "Find My", account: "Apple", requests: "Apple" };
  if (other && !apple) return { network: "Find Hub", account: "Google", requests: "Google" };
  return { network: "your providers", account: "tracking", requests: "your providers" };
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
  if (poll) poll.title = `Queries ${w.requests} once, now`;
  const observed = $("card-observed-label");
  if (observed) observed.textContent = `Last observed by ${w.network}`;
  const heading = $("device-modal-title");
  if (heading) heading.textContent = `Devices on this ${w.account} account`;
  const note = $("device-modal-note");
  if (note) {
    note.textContent =
      `Tick every tracker you want polled. Each tracked device costs one ${w.requests} ` +
      "request per poll cycle, so the request rate rises with the number you tick. " +
      "Untracking keeps a device's existing history — it just stops being polled.";
  }
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

/** Open the Devices dialog. */
export async function openDevices() {
  await loadDevices();
  renderDeviceModal();
  $("device-modal").classList.remove("hidden");
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
    btn.textContent = "Polling…";
    try {
      const r = await postJson("/api/poll-now");
      const lines = r.results.map((x) => `${x.device_name}: ${x.status}${x.observations_new ? ` (+${x.observations_new})` : ""}`);
      showAlert(`Polled ${r.devices_polled} device(s) — ${r.observations_new} new. ${lines.join(" · ")}`, "warn");
      await reload();
    } catch (err) {
      showAlert(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "Poll Now";
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
    btn.textContent = "Asking your providers…";
    try {
      const r = await postJson("/api/devices/refresh");
      await loadDevices();
      renderDeviceModal();
      // Name the providers that answered. "on the account" was singular and
      // Google-shaped while the button said "your providers" (round 2 F4);
      // a partial failure must say which one was skipped, not stay silent.
      const asked = (r.providers || []).length;
      const failed = Object.keys(r.errors || {});
      let msg = `Found ${r.found} device(s) across ${asked} provider(s).`;
      if (failed.length) msg += ` ${failed.join(", ")} could not be reached.`;
      showAlert(msg, "warn");
    } catch (err) {
      showAlert(`Could not refresh devices: ${err.message}`, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "Refresh from your providers";
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
          ? `Tracking ${r.tracked_count} device(s) — about ${r.requests_per_hour} ${providerWording().requests} requests/hour.`
          : `No devices tracked. The poller will not query ${providerWording().requests}.`,
        "warn"
      );
      await reload();
    } catch (err) {
      showAlert(err.message, "err");
    }
  });
}
