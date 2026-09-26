/*
 * Device list, the device-manager modal, and manual poll wiring.
 *
 * Purpose    : List Find Hub devices, choose which are tracked, and show the
 *              resulting request-rate estimate.
 * Constraints: `poll-now` is the only control wired here that queries Google.
 */
"use strict";

import { $, state, colorFor, displayName, showAlert } from "./state.js";
import { api } from "./api.js";
import { applyHashRoute, reload } from "./main.js";
import { loadPresence } from "./places.js";
import { plural, t } from "./i18n.js";
import { renderBadge } from "./components/badge.js";
import { initDialog, openEditDialog } from "./devices_dialog.js";
import { trapFocus } from "./components/dialog-trap.js";
import { providerWording, syncProviderChrome, syncProviderNotice } from "./provider_chrome.js";
import { pollNow, refreshFromProviders, saveTrackedDevices } from "./devices_actions.js";

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

/** Longest device name the Show list prints before cutting it with "…". */
const OPTION_NAME_MAX = 32;

/** `text` cut to `max` characters with a trailing ellipsis. */
function ellipsize(text, max) {
  const value = String(text);
  return value.length > max ? value.slice(0, max - 1).trimEnd() + "…" : value;
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
      const full = displayName(d) + " (" + providerLabel(d.provider) + ")" + (d.is_tracked ? "" : t("devices.notPolledSuffix"));
      // UAT6-N09: a <select> is as wide as its longest option, and CSS cannot
      // ellipsize inside the open list. Cut long names here; the title keeps
      // the whole thing for hover.
      opt.textContent = ellipsize(displayName(d), OPTION_NAME_MAX) + full.slice(displayName(d).length);
      opt.title = full;
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
  const cell = el("span", "d-names");
  const secondary = d.label ? d.name : d.device_id;
  cell.append(el("span", "d-name", d.label || d.name), el("span", "d-id", secondary));
  return cell;
}

/** The Edit button. The row is a <label>, so the click must not also tick it. */
function editButton(d) {
  const edit = el("button", "fp-device-edit btn btn-tiny", t("common.edit"));
  edit.type = "button";
  // UAT2 N11: this read "Edit Moto Tag 1" (the raw provider name) even when
  // the tag had a label -- every other surface reads displayName() first.
  edit.setAttribute("aria-label", t("devices.card.edit", { name: displayName(d) }));
  edit.addEventListener("click", (e) => {
    e.preventDefault();
    openEditDialog(d.device_id, d);
  });
  return edit;
}

/** One row of the Devices dialog: checkbox, badge and name with Edit beside
 * them, then the observation count and provider on a line of their own
 * (UAT6-N11: at phone width the name had one word per line). Layout lives in
 * style.css's .device-row rules; places.js appends its presence chip last. */
function deviceRow(d) {
  const row = el("div", "device-row");
  row.dataset.deviceId = d.device_id;
  const check = el("input");
  check.type = "checkbox";
  check.id = "chk-" + d.device_id;
  check.value = d.device_id;
  check.checked = d.is_tracked;
  check.addEventListener("change", updateModalRate);

  const label = el("label", "d-main");
  label.htmlFor = check.id;
  label.append(check, badgeCell(d), nameCell(d));

  const count = Number(d.observation_count) || 0;
  const obs = el("span", "d-obs", plural("devices.obsCount", count, { n: count }));
  const providerClass = "fp-provider-badge fp-provider-badge--" + (d.provider || "unknown");
  const provider = el("span", providerClass, providerLabel(d.provider));
  const meta = el("span", "d-meta");
  meta.append(obs, provider);
  row.append(label, editButton(d), meta);
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
    ? plural("devices.rateTracked", checked, { count: checked, rate, requests: w.requests, interval })
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

/** Wire the device filter, device-manager modal, and manual poll button. */
export function wireDeviceControls() {
  initDialog(async () => {
    await loadDevices();
    renderDeviceModal();
    // A saved label/icon/colour used to sit stale on the dashboard behind
    // the dialog until the next manual reload (UAT U14): the map markers,
    // timeline track heads, topbar name and cards all read state.devices,
    // so the same reload() the toolbar's other actions use catches them up.
    await reload();
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
