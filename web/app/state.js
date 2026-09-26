/*
 * Shared mutable state, the DOM shorthand, and dependency-free formatting
 * helpers used by every other module.
 *
 * Purpose    : Single source of truth for dashboard state (current day,
 *              device filter, map/marker handles, lock state, etc.) plus the
 *              small pure helpers ($ , fmt*, colorFor, showAlert, applyTheme)
 *              that have no dependency on any sibling module.
 * Constraints: No imports from sibling modules except i18n.js (CF-P2-E9-1:
 *              the fmt* helpers route their unit ladder through t()/plural()
 *              instead of hardcoding English) — i18n.js itself has no
 *              sibling imports beyond the bundled catalog, so this stays a
 *              leaf every other module can safely import FROM, never the
 *              reverse.
 */
"use strict";

import { t, plural } from "./i18n.js";

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
  /** The dashboard's group select (#fp-group-select): a group id, or "" for
   *  every tracked device. Set alongside groupMembers by groups.js. */
  groupFilter: "",
  /** Set<device_id> of the selected group's members, or null when no group
   *  is selected. visibleTracks() below reads this to narrow the map and
   *  timeline without a second network round trip (UAT U8). */
  groupMembers: null,
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
  /**
   * Whether bootDashboard() has run at least once this page load.
   *
   * The onboarding wizard's onDone uses it to tell a true first launch (boot
   * the dashboard now) from a re-entry through Settings (the dashboard is
   * already live; booting it again would stack a second refresh timer).
   */
  dashboardBooted: false,
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

/** Resolves the saved theme, migrating the legacy `bt.theme` key if needed.
 *  Nothing stored follows the OS (UAT6-N20), not a fixed dark theme. */
export function getStoredTheme() {
  return migrateLegacyKey("bt.theme", "findplus.theme") || "system";
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

/**
 * "5 min" / "94 min" / "1 h 34 min" / "3 h" / "2 d" — the one age ladder
 * every surface uses.
 *
 * groups.js, Model.swift's formatAge and formatStaleGap all switch to days at
 * 48 h; places.js had its own switching at 24 h, so a 30-hour gap read "30 h"
 * in Groups and "1 d" in Places (E1 honesty round 3 F12). Below 120 minutes
 * this stays in minutes rather than rounding to the nearest hour: the Groups
 * stale badge used to floor 94 minutes to "1 h" while the presence note beside
 * it (server-formatted, always raw minutes) read "(81 min ago)" for a
 * different member -- two ages in the same panel that looked contradictory
 * for no reason (UAT4 N33). 120 minutes and over still switches to hours,
 * carrying a minute remainder rather than dropping it.
 */
export function fmtAgeMinutes(minutes) {
  if (minutes == null || Number.isNaN(minutes)) return t("units.unknown");
  const whole = Math.max(0, Math.floor(minutes));
  if (whole < 120) return t("units.minutesShort", { n: whole });
  const hours = Math.floor(whole / 60);
  if (hours >= 48) return t("units.daysShort", { n: Math.floor(hours / 24) });
  const remainder = whole % 60;
  return remainder
    ? t("units.hoursMinutesShort", { h: hours, m: remainder })
    : t("units.hoursShort", { n: hours });
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
  if (seconds === null || seconds === undefined) return t("common.emptyValue");
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return t("units.seconds", { n: s });
  const m = Math.round(s / 60);
  if (m < 60) return t("units.minutes", { n: m });
  const h = Math.floor(m / 60);
  const rem = m % 60;
  if (h < 24) return rem ? t("units.hoursMinutes", { h, m: rem }) : t("units.hours", { n: h });
  const d = Math.floor(h / 24);
  return `${plural("units.days", d, { n: d })} ${t("units.hours", { n: h % 24 })}`;
}

export function fmtDistance(meters) {
  if (meters === null || meters === undefined) return null;
  const miles = meters / 1609.344;
  if (miles < 0.1) return t("units.meters", { n: Math.round(meters) });
  return t("units.miles", { n: miles.toFixed(miles < 10 ? 2 : 1) });
}

export function todayLocal() {
  const d = new Date();
  return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

/**
 * The identity string every surface shows for a device: the label the user
 * gave it, or the provider's own name, or its raw id -- never the caller's
 * own ad-hoc fallback chain (UAT U6: Show dropdown, group members, rule
 * forms, rules table, cards, map popups and timeline rows all read the same
 * value). Returns null for no device at all, so a caller with its own
 * further fallback (a track's stored `device_name`, a group member's own
 * `name`) can still chain onto it with `displayName(device) || ...`.
 */
export function displayName(device) {
  if (!device) return null;
  return device.label || device.name || device.device_id || null;
}

/**
 * The timeline's tracks, narrowed to the selected group's members.
 *
 * `/api/timeline` already returns every tracked device's track in one
 * response, and a group's member device_ids are already loaded (GET
 * /api/groups), so the dashboard's group select filters map.js/timeline.js
 * client-side rather than adding a second, group-scoped fetch (UAT U8).
 */
export function visibleTracks(tracks) {
  if (!state.groupMembers) return tracks;
  return tracks.filter((track) => state.groupMembers.has(track.device_id));
}

export function colorFor(deviceId) {
  if (!state.colors.has(deviceId)) {
    state.colors.set(deviceId, TRACK_COLORS[state.colors.size % TRACK_COLORS.length]);
  }
  return state.colors.get(deviceId);
}

/**
 * The banner under the cards. `extra` is optional: `action` ({label, run})
 * adds one in-app button after the sentence, and `hint` a smaller secondary
 * line (UAT6-N06/N07: the fix a user can make in the app comes first, a
 * terminal command only ever as that secondary hint).
 */
export function showAlert(message, kind, extra = {}) {
  const el = $("alert");
  if (!message) { el.classList.add("hidden"); el.textContent = ""; return; }
  const text = document.createElement("span");
  text.className = "alert-text";
  text.textContent = message;
  el.replaceChildren(text);
  if (extra.action) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-tiny alert-action";
    btn.textContent = extra.action.label;
    btn.addEventListener("click", extra.action.run);
    el.appendChild(btn);
  }
  if (extra.hint) {
    const hint = document.createElement("span");
    hint.className = "alert-hint";
    hint.textContent = extra.hint;
    el.appendChild(hint);
  }
  el.className = `alert ${kind === "warn" ? "warn" : ""}`;
}

/* ---------------------------------------------------------------- theme */

const OS_LIGHT = "(prefers-color-scheme: light)";
let chosenTheme = null;

/** Applied before first paint from localStorage, then reconciled with the
 *  server. "system" keeps following the OS while the page stays open. */
export function applyTheme(theme) {
  if (chosenTheme === null) {
    window.matchMedia(OS_LIGHT).addEventListener("change", () => {
      if (chosenTheme === "system") applyTheme("system");
    });
  }
  chosenTheme = theme;
  const resolved = theme === "system" ? (window.matchMedia(OS_LIGHT).matches ? "light" : "dark") : theme;
  document.documentElement.setAttribute("data-theme", resolved);
  try { localStorage.setItem("findplus.theme", theme); } catch (_) { /* private mode */ }
}
