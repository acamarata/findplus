/*
 * "Draw likely roads": the filter-bar switch, its privacy line, and route fetching.
 *
 * Purpose    : Road routes are opt in twice. A routing server address must be set
 *              in Settings, and the person must tick this box. Until an address
 *              exists the box is disabled and says why, with a link to Settings.
 *              With the box ticked, each trip's route is asked for lazily, two at
 *              a time, the picked trip first.
 * Inputs     : #roads-group, #toggle-roads, #roads-note (index.html), the trips
 *              of the day on screen, honesty.routingPrivacy and honesty.routeLikely.
 * Outputs    : roadsWanted(), syncRoadsUi(), queueRoutes() and the map note.
 * Constraints: The choice is NOT remembered across page loads: ticking it sends
 *              sightings to the routing server, so it starts off every time.
 *              Nothing is requested while locked or with the box off.
 */
"use strict";

import { $, state } from "./state.js";
import { t } from "./i18n.js";
import { loadRoute, resetRoutes, routingOn } from "./trips_data.js";

const PARALLEL = 2;
let wanted = false;
let runId = 0;

export const roadsWanted = () => wanted && routingOn() === true;

/** The one-line note on the map: shown only while a road route is drawn. */
export function syncRouteNote(show) {
  const pane = document.querySelector(".map-pane");
  if (!pane) return;
  let note = document.getElementById("route-note");
  if (!show) {
    if (note) note.remove();
    return;
  }
  if (!note) {
    note = document.createElement("p");
    note.id = "route-note";
    note.className = "map-note route-note";
    note.setAttribute("role", "status");
    pane.appendChild(note);
  }
  note.textContent = t("honesty.routeLikely");
}

/** Show or hide the switch for the current view, and enable it only when a server is set. */
export function syncRoadsUi(storyVisible) {
  const group = $("roads-group");
  const note = $("roads-note");
  if (!group || !note) return;
  const known = routingOn();
  const on = known === true;
  group.hidden = !storyVisible;
  note.hidden = !storyVisible;
  $("toggle-roads").disabled = !on;
  if (!on) wanted = false;
  $("toggle-roads").checked = wanted;
  note.replaceChildren(document.createTextNode(`${t("honesty.routingPrivacy")} `));
  if (known === false) {
    const link = document.createElement("a");
    link.href = "#settings";
    link.textContent = t("trips.roadsSetup");
    note.append(document.createTextNode(`${t("trips.roadsNeedServer")} `), link);
  }
}

/** Ask for each trip's route, `PARALLEL` at a time; `done()` runs after each answer. */
export async function queueRoutes(device, day, trips, firstId, done) {
  if (!roadsWanted()) return;
  const mine = ++runId;
  const gen = state.lockGeneration;
  const order = [...trips].sort((a, b) => (b.id === firstId) - (a.id === firstId));
  const todo = [...order];
  const worker = async () => {
    while (todo.length && mine === runId && state.lockGeneration === gen) {
      const trip = todo.shift();
      const result = await loadRoute(device, day, trip.id);
      if (result && mine === runId && state.lockGeneration === gen) done();
    }
  };
  await Promise.all(Array.from({ length: PARALLEL }, worker));
}

/** Wire the checkbox. `onChange()` redraws the story and starts fetching. */
export function wireRoads(onChange) {
  const box = $("toggle-roads");
  if (!box) return;
  box.addEventListener("change", () => {
    wanted = box.checked;
    runId += 1;
    if (!wanted) resetRoutes();
    onChange();
  });
}

/** Lock purge: the choice is gone with everything else. */
export function purgeRoads() {
  wanted = false;
  runId += 1;
  syncRouteNote(false);
  const note = $("roads-note");
  if (note) note.replaceChildren();
}
