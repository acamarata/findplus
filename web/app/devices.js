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
  $("device-rate").textContent = checked
    ? `${checked} device(s) tracked → about ${rate} Google requests per hour, polled sequentially every ${interval} min.`
    : "Nothing tracked — the poller will not query Google at all.";
}

export async function loadDevices() {
  const body = await api("/api/devices");
  state.devices = body.devices;
  state.devices.forEach((d) => colorFor(d.device_id));
  renderDeviceFilter();
  syncProviderNotice();
  return body;
}

/**
 * Show the Apple sentence in the footer only when an Apple tracker is present.
 *
 * The footer used to render the Find Hub sentence unconditionally, so someone
 * tracking only AirTags read that their tags report "through Google Find Hub
 * network" (E1 honesty pass F1). Both sentences come verbatim from
 * /api/config.notices, so honesty.py stays the single source.
 */
export function syncProviderNotice() {
  const el = $("apple-notice");
  if (!el) return;
  const apple = state.config?.notices?.apple;
  const hasApple = state.devices.some((d) => d.provider === "apple-find-my");
  el.textContent = hasApple && apple ? apple : "";
  el.hidden = !(hasApple && apple);
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
      showAlert(`Found ${r.found} device(s) on the account.`, "warn");
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
          ? `Tracking ${r.tracked_count} device(s) — about ${r.requests_per_hour} Google requests/hour.`
          : "No devices tracked. The poller will not query Google.",
        "warn"
      );
      await reload();
    } catch (err) {
      showAlert(err.message, "err");
    }
  });
}
