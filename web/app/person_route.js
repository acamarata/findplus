/*
 * Opening and closing the Person page: the tab panel, the shared map and focus.
 *
 * Purpose    : `#/person/<id>?date=...` shows the Person panel in the side pane
 *              and borrows the dashboard map. Any other hash puts the previous
 *              tab and the dashboard's own map layers back.
 * Inputs     : A parsed route ({id, date}) from main.js's applyHashRoute().
 * Outputs    : showPerson(route), hidePerson(); `state.personView` is true while
 *              the page is open (map.js's renderMap() stands aside meanwhile).
 * Constraints: The page has no tab button, so the tab that was active stays the
 *              one Tab stop of the tab bar. Leaving restores it. First open moves
 *              keyboard focus to the person's name so a screen reader hears it.
 */
"use strict";

import { $, state, todayLocal } from "./state.js";
import { t } from "./i18n.js";
import { switchTab } from "./main.js";
import { wireDateBar } from "./person_datebar.js";
import { dropLayers, ensureLayers, loadPerson, reload } from "./person_page.js";
import { showPageOnPhone } from "./person_map.js";
import { refreshPeopleCache } from "./person_links.js";

let wired = false;
let previousTab = "dashboard";
let seenGroups = null;

const activeTab = () => document.querySelector(".fp-tabs .fp-tab.active");

function enter() {
  const active = activeTab();
  previousTab = active ? active.dataset.tab : "dashboard";
  state.personView = true;
  $("app-shell").classList.add("person-view");
  if (state.layer) state.layer.remove();
  if (state.legend) { state.legend.remove(); state.legend = null; }
}

function wireOnce() {
  if (wired) return;
  wired = true;
  wireDateBar();
  // A person edited in the Groups dialog: names and trackers on this page are stale.
  document.addEventListener("fp:groups-loaded", (e) => {
    const changed = seenGroups !== null && seenGroups !== e.detail;
    seenGroups = e.detail;
    if (!changed) return;
    refreshPeopleCache();
    if (state.personView && !state.locked) reload();
  });
}

/** Show the Person page for `route` ({id, date|null}). */
export async function showPerson(route) {
  wireOnce();
  const first = !state.personView;
  if (first) enter();
  switchTab("person");
  const stop = document.querySelector(`.fp-tabs .fp-tab[data-tab="${previousTab}"]`);
  if (stop) stop.tabIndex = 0;
  ensureLayers();
  const done = loadPerson(route.id, route.date || todayLocal());
  await done;
  if (first) {
    $("person-name")?.focus({ preventScroll: true });
    showPageOnPhone();
  }
}

/** Leave the Person page: restore the tab and the dashboard's map layers. */
export async function hidePerson() {
  if (!state.personView) return;
  state.personView = false;
  $("app-shell").classList.remove("person-view");
  dropLayers();
  if (state.layer && state.map) state.layer.addTo(state.map);
  if (state.map) state.map.getContainer().setAttribute("aria-label", t("map.label"));
  switchTab(previousTab);
  const { renderMap } = await import("./map.js");
  renderMap({ fit: false });
}
