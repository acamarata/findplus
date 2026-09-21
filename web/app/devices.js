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
import { t } from "./i18n.js";
import { renderBadge } from "./components/badge.js";
import { initDialog, openEditDialog } from "./devices_dialog.js";
import { trapFocus } from "./components/dialog-trap.js";
import { providerWording, syncProviderChrome, syncProviderNotice } from "./provider_chrome.js";

/** The focus trap for #device-modal while it is open, or null. */
let deviceTrap = null;

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

/** `<span class="cls">text</span>` and friends, the shape every cell below takes. */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** The colour disc. A device seeded without the 0007 columns still renders. */
function badgeCell(d) {
  const cell = el("span", "fp-device-badge");
  const color = d.color || colorFor(d.device_id);
  cell.appendChild(renderBadge({ icon: d.icon || "letter", color, label: d.label, name: d.name, size: 24 }));
  return cell;
}

/** The label (or the name), with the raw device name below it once a label is set. */
function nameCell(d) {
  const cell = el("span");
  const secondary = d.label ? d.name : d.device_id;
  cell.append(el("span", "d-name", d.label || d.name), el("br"), el("span", "d-id", secondary));
  return cell;
}

/** The Edit button. The row is a <label>, so the click must not also tick it. */
function editButton(d) {
  const edit = el("button", "fp-device-edit btn btn-tiny", t("common.edit"));
  edit.type = "button";
  edit.setAttribute("aria-label", t("devices.card.edit", { name: d.name }));
  edit.addEventListener("click", (e) => {
    e.preventDefault();
    openEditDialog(d.device_id, d);
  });
  return edit;
}

/** One row of the Devices dialog. */
function deviceRow(d) {
  const row = el("div", "device-row");
  row.dataset.deviceId = d.device_id;
  const check = el("input");
  check.type = "checkbox";
  check.id = "chk-" + d.device_id;
  check.value = d.device_id;
  check.checked = d.is_tracked;
  check.addEventListener("change", updateModalRate);
  
  const label = el("label");
  label.htmlFor = check.id;
  label.style.display = "flex";
  label.style.alignItems = "center";
  label.style.gap = "10px";
  label.style.cursor = "pointer";
  label.append(check, badgeCell(d), nameCell(d));
  
  const obs = el("span", "d-obs", t("devices.obsCount", { n: Number(d.observation_count) || 0 }));
  const providerClass = "fp-provider-badge fp-provider-badge--" + (d.provider || "unknown");
  const provider = el("span", providerClass, providerLabel(d.provider));
  row.append(label, obs, provider, editButton(d));
  return row;
}

export function renderDeviceModal() {
  const host = $("device-list");
  while (host.firstChild) host.removeChild(host.firstChild);
  if (!state.devices.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = t("devices.emptyState");
    host.appendChild(empty);
  }
  state.devices.forEach((d) => host.appendChild(deviceRow(d)));
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

export { providerWording, syncProviderChrome, syncProviderNotice } from "./provider_chrome.js";

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
    deviceTrap = trapFocus($("device-modal"), closeDevices);
  }
}

/** Hide the dialog and hand focus back to whatever opened it. */
export function closeDevices() {
  $("device-modal").classList.add("hidden");
  if (deviceTrap) {
    deviceTrap.release();
    deviceTrap = null;
  }
}

/** Query every provider once, now, and say what came back. */
async function pollNow() {
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
}

/**
 * Re-read the device list from every provider the user is signed in to.
 *
 * A partial failure names the provider that could not be reached rather than
 * staying silent, and the button says "your providers" whichever ones answered
 * (E1 honesty round 2 F4).
 */
async function refreshFromProviders() {
  const btn = $("btn-refresh-devices");
  btn.disabled = true;
  btn.textContent = t("devices.askingProvidersLabel");
  try {
    const r = await postJson("/api/devices/refresh");
    await loadDevices();
    renderDeviceModal();
    const failed = Object.keys(r.errors || {});
    let msg = t("devices.refreshFound", { found: r.found, providers: (r.providers || []).length });
    if (failed.length) msg += t("devices.refreshUnreachable", { names: failed.join(", ") });
    showAlert(msg, "warn");
  } catch (err) {
    showAlert(t("devices.refreshFailed", { message: err.message }), "err");
  } finally {
    btn.disabled = false;
    btn.textContent = t("devices.refreshProvidersLabel");
  }
}

/** Save the ticked set and report the request rate it implies. */
async function saveTrackedDevices() {
  const ids = [...document.querySelectorAll("#device-list input:checked")].map((i) => i.value);
  try {
    const r = await postJson("/api/devices/track", { device_ids: ids });
    closeDevices();
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
}

/** Wire the device filter, device-manager modal, and manual poll button. */
export function wireDeviceControls() {
  initDialog(async () => {
    await loadDevices();
    renderDeviceModal();
  });

  $("device-filter").addEventListener("change", async (e) => {
    state.deviceFilter = e.target.value;
    localStorage.setItem("findplus.deviceFilter", state.deviceFilter);
    await reload();
  });

  $("btn-poll").addEventListener("click", pollNow);

  // --- device manager ---
  $("btn-devices").addEventListener("click", openDevices);
  window.addEventListener("hashchange", applyHashRoute);
  $("btn-close-devices").addEventListener("click", closeDevices);
  $("device-modal").addEventListener("click", (e) => {
    if (e.target.id === "device-modal") closeDevices();
  });

  $("btn-track-all").addEventListener("click", () => {
    document.querySelectorAll("#device-list input").forEach((i) => { i.checked = true; });
    updateModalRate();
  });
  $("btn-track-none").addEventListener("click", () => {
    document.querySelectorAll("#device-list input").forEach((i) => { i.checked = false; });
    updateModalRate();
  });

  $("btn-refresh-devices").addEventListener("click", refreshFromProviders);
  $("btn-save-devices").addEventListener("click", saveTrackedDevices);
}
