/*
 * The side panel's tab row: Latest · People · Activity · Places · Alerts.
 *
 * Purpose    : The one place tab switching happens. It toggles the `.fp-tab` /
 *              `.fp-tab-panel` pair (WAI-ARIA tabs: aria-selected + roving
 *              tabindex, see components/tabs_a11y.js), remembers the last tab
 *              per viewer, maps deep links to tabs, and tells the pane that
 *              just became visible to mount (see the pane contract below).
 * Inputs     : switchTab(tab) from the tab row, the phone bottom bar
 *              (components/tabbar.js), the hash router (main.js) and any
 *              module that wants to send the user somewhere.
 * Outputs    : DOM state, the `findplus:tab-changed` event (detail {tab}),
 *              localStorage `findplus.panelTab` (try/catch, never required),
 *              and one call to the shown pane's mount function.
 * Constraints: Old names still work: "dashboard" is "latest", "groups" is
 *              "people" (and `#/groups` is `#/people`). "person" is the Person
 *              page's own panel; it is never remembered.
 *
 * PANE CONTRACT (for the Latest, People and Activity builders)
 *   latest   container #tab-latest   module latest_pane.js    mountLatest / refreshLatest
 *   people   container #tab-people   module people_pane.js    mountPeople / refreshPeople
 *   activity container #tab-activity module activity_pane.js  mountActivity / refreshActivity
 *   - mountX(container): called once at boot (after the first day load) and
 *     again every time the tab becomes visible. Idempotent and cheap; may be
 *     async; build the DOM inside `container` only.
 *   - refreshX(): called when fresh data landed (event `findplus:data-refreshed`,
 *     fired by live_refresh.js after the device list and the day were reloaded,
 *     and by loadDay()'s callers) while the pane is the visible one. Never
 *     fetch from a timer of your own.
 *   - Other events a pane may listen to: `findplus:accounts-changed` (sign-in
 *     changed; live_refresh.js already reloads and then fires
 *     data-refreshed), `findplus:people-changed` (a person was added or
 *     edited from the app bar or another pane), `findplus:tab-changed`.
 *   - Lock: purge your DOM in the same place the other panes purge (lock.js).
 */
"use strict";

import { mountLatest, refreshLatest } from "./latest_pane.js";
import { mountPeople, refreshPeople } from "./people_pane.js";
import { mountActivity, refreshActivity } from "./activity_pane.js";

export const TABS = ["latest", "people", "activity", "places", "alerts"];
const ALIAS = { dashboard: "latest", groups: "people" };
const PREF_KEY = "findplus.panelTab";
const PANES = {
  latest: ["tab-latest", mountLatest, refreshLatest],
  people: ["tab-people", mountPeople, refreshPeople],
  activity: ["tab-activity", mountActivity, refreshActivity],
};

/** "dashboard" and "groups" are the old names of "latest" and "people". */
export const normalizeTab = (tab) => ALIAS[tab] || tab;

/** `#/people` or the legacy `#places` -> "people" / "places"; anything else -> null. */
export function tabFromHash(hash) {
  const m = /^#\/?([a-z]+)$/.exec(hash || "");
  const tab = m ? normalizeTab(m[1]) : null;
  return tab && TABS.includes(tab) ? tab : null;
}

/** The remembered tab, or null (storage can be blocked or empty). */
export function savedTab() {
  try {
    const tab = normalizeTab(localStorage.getItem(PREF_KEY));
    return TABS.includes(tab) ? tab : null;
  } catch (_) {
    return null;
  }
}

function remember(tab) {
  try { localStorage.setItem(PREF_KEY, tab); } catch (_) { /* private mode */ }
}

/** Mount (or re-show) the pane that owns `tab`, if it has an adapter. */
export function mountPane(tab) {
  const entry = PANES[tab];
  const container = entry && document.getElementById(entry[0]);
  if (!container) return Promise.resolve();
  return Promise.resolve(entry[1](container)).catch((err) => console.warn(`pane ${tab} failed to mount`, err));
}

/** The visible tab's name, or null while the Person page is up. */
export function activeTab() {
  const el = document.querySelector(".fp-tabs .fp-tab.active");
  return el ? el.dataset.tab : null;
}

/**
 * Switch the active `.fp-tab` / `.fp-tab-panel` pair.
 *
 * The one place tab switching happens: the tab row's buttons and the phone
 * tier's bottom bar both call this rather than keeping two copies.
 */
export function switchTab(tabName, { remember: keep = true } = {}) {
  const tab = normalizeTab(tabName);
  document.querySelectorAll(".fp-tabs .fp-tab").forEach((b) => {
    const active = b.dataset.tab === tab;
    b.classList.toggle("active", active);
    // WAI-ARIA tabs (U31): only the active tab is a Tab stop (tabs_a11y.js).
    b.setAttribute("aria-selected", String(active));
    b.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll(".fp-tab-panel").forEach((p) => {
    p.hidden = p.id !== "tab-" + tab;
  });
  if (keep && TABS.includes(tab)) remember(tab);
  window.dispatchEvent(new CustomEvent("findplus:tab-changed", { detail: { tab } }));
  mountPane(tab);
}

/** Boot: the hash names a tab, else the remembered one, else Latest. */
export function restoreTab() {
  // A deep link or the boot restore never overwrites the remembered tab; only a click does.
  switchTab(tabFromHash(window.location.hash) || savedTab() || "latest", { remember: false });
}

/** Fire after fresh data landed: the visible pane redraws itself. */
export function announceDataRefreshed() {
  window.dispatchEvent(new CustomEvent("findplus:data-refreshed"));
}

/** Wire the data-refreshed event to the visible pane's refresh hook (once, at boot). */
export function wirePaneRefresh() {
  window.addEventListener("findplus:data-refreshed", () => {
    const entry = PANES[activeTab()];
    if (entry) Promise.resolve(entry[2]()).catch((err) => console.warn("pane refresh failed", err));
  });
}
