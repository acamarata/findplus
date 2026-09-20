/*
 * Shared mutable state, the DOM shorthand, and dependency-free formatting
 * helpers used by every other module.
 *
 * Purpose    : Single source of truth for dashboard state (current day,
 *              device filter, map/marker handles, lock state, etc.) plus the
 *              small pure helpers ($ , fmt*, colorFor, showAlert, applyTheme)
 *              that have no dependency on any sibling module.
 * Constraints: No imports from sibling modules — every other module imports
 *              FROM here, never the reverse, so this stays the leaf of the
 *              dependency graph.
 */
"use strict";

/** Per-device track colours, chosen to stay distinguishable on OSM tiles. */
export const TRACK_COLORS = [
  "#4f8cf7", "#e7663f", "#37c67a", "#c77ae6",
  "#e7b53f", "#3fc9d6", "#e64f7a", "#8fb43f",
];

export const state = {
  config: null,
  day: null,
  timeline: null,
  devices: [],
  deviceFilter: migrateLegacyKey("bt.deviceFilter", "findplus.deviceFilter") || "",
  colors: new Map(),
  selectedId: null,
  movementOnly: false,
  map: null,
  layer: null,
  markers: new Map(),
  refreshTimer: null,
  settings: null,
  locked: false,
  idleTimer: null,
  idleMinutes: 0,
  /** View to restore verbatim after an unlock. */
  resume: null,
};

export const $ = (id) => document.getElementById(id);

/**
 * One-time localStorage key migration: the dashboard used to be called
 * "bike-tracker" (`bt.*` keys). Reads the new key if present, otherwise
 * copies the legacy key's value across and removes the legacy key. Safe to
 * call every load — a no-op once migrated.
 */
function migrateLegacyKey(oldKey, newKey) {
  try {
    const current = localStorage.getItem(newKey);
    if (current !== null) return current;
    const legacy = localStorage.getItem(oldKey);
    if (legacy !== null) {
      localStorage.setItem(newKey, legacy);
      localStorage.removeItem(oldKey);
    }
    return legacy;
  } catch (_) {
    return null;
  }
}

/** Resolves the saved theme, migrating the legacy `bt.theme` key if needed. */
export function getStoredTheme() {
  return migrateLegacyKey("bt.theme", "findplus.theme") || "dark";
}

/* ----------------------------------------------------------- formatting */

/**
 * Escape text for an innerHTML template. Prefer textContent where you can.
 *
 * A tracker's `name` and an observation's `source` come from the provider, so
 * anyone who can rename a tag in the linked Google or Apple account writes
 * into the watcher's dashboard. Most modules build their DOM with
 * createElement and are safe by construction; the five template sites that
 * could not be converted cheaply pass their untrusted values through here
 * (E1 security round 3 F1). The CSP was the only reason the injected markup
 * did not execute -- it was still enough to smuggle a checked <input> into
 * the device list, which the Save button then POSTs as a tracked device.
 */
export function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function fmtDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} sec`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  if (h < 24) return rem ? `${h} hr ${rem} min` : `${h} hr`;
  const d = Math.floor(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ${h % 24} hr`;
}

export function fmtDistance(meters) {
  if (meters === null || meters === undefined) return null;
  const miles = meters / 1609.344;
  if (miles < 0.1) return `${Math.round(meters)} m`;
  return `${miles.toFixed(miles < 10 ? 2 : 1)} mi`;
}

export function todayLocal() {
  const d = new Date();
  return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function colorFor(deviceId) {
  if (!state.colors.has(deviceId)) {
    state.colors.set(deviceId, TRACK_COLORS[state.colors.size % TRACK_COLORS.length]);
  }
  return state.colors.get(deviceId);
}

export function showAlert(message, kind) {
  const el = $("alert");
  if (!message) { el.classList.add("hidden"); return; }
  el.textContent = message;
  el.className = `alert ${kind === "warn" ? "warn" : ""}`;
}

/* ---------------------------------------------------------------- theme */

/** Applied before first paint from localStorage, then reconciled with the server. */
export function applyTheme(theme) {
  const resolved =
    theme === "system"
      ? (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")
      : theme;
  document.documentElement.setAttribute("data-theme", resolved);
  localStorage.setItem("findplus.theme", theme);
}
