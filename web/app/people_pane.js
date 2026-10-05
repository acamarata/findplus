/*
 * People pane adapter (People tab).
 *
 * Purpose    : The mount point the People builder rewrites. TODAY it is the old
 *              Groups panel: people cards, the groups list (#fp-groups-list),
 *              the "Find+ found people" suggestions card, the presence panel
 *              and the Add group button, all in the static markup of
 *              #tab-people (web/partials/groups.html), driven by groups.js.
 * Inputs     : mountPeople(container): container is #tab-people.
 * Outputs    : First call: groups.js init() (selector, overlay layer, cards,
 *              dialog wiring). Later calls return the same promise.
 * Constraints (contract, see panel_tabs.js for the full text):
 *   - mountPeople(container) runs at boot (awaited by main.js before the
 *     dashboard loads, because groups.js owns the map overlay and the group
 *     selector) and again each time the tab is shown; idempotent.
 *     refreshPeople() reloads the cards and the suggestions on
 *     `findplus:data-refreshed` while this tab is visible.
 *   - Events: `findplus:people-changed` (fired after Add > Person saves),
 *     findplus:accounts-changed, findplus:data-refreshed, fp:groups-loaded
 *     (document event from groups.js with the groups signature).
 *   - Existing ids kept: #fp-add-group-btn, #fp-groups-list, #fp-people-suggest,
 *     #fp-presence-panel, #fp-group-legend, #fp-places-backfill.
 *   - The app bar's Add > Person opens person_editor.js openPersonCreate().
 */
"use strict";

import { state } from "./state.js";

let initDone = null;

/** First call wires groups.js (once, even if called twice quickly). */
export function mountPeople(container) {
  if (!container) return Promise.resolve();
  if (initDone) return initDone;
  initDone = import("./groups.js").then((m) => m.init(state.map, document.getElementById("device-list")));
  return initDone;
}

export async function refreshPeople() {
  if (state.locked) return;
  const groups = await import("./groups.js");
  await groups.loadGroups();
  const suggest = await import("./people_suggest.js");
  await suggest.load();
}

window.addEventListener("findplus:people-changed", () => {
  if (initDone && !state.locked) refreshPeople().catch(() => {});
});
