/*
 * A one-line note on the map itself when it has nothing to draw.
 *
 * Purpose    : With no observations the map is a bare world tile. Beside the
 *              Show / Group / Day controls that read as broken, so say why in
 *              a small label on the map: locked, nothing recorded yet, or a
 *              quiet day. The right-hand pane carries the full message and the
 *              action; this is only the glance.
 * Inputs     : state.status (status_view.js), state.markers (map.js fills it
 *              with one marker per drawn point), state.locked.
 * Outputs    : #map-empty inside .map-pane, created on first use.
 * Constraints: Decorative (aria-hidden, no pointer events): the pane beside it
 *              is the accessible copy. Never shown while locked or before the
 *              first status, so it cannot flash a wrong reason.
 */
"use strict";

import { state } from "./state.js";
import { t } from "./i18n.js";
import { emptyKind } from "./poll_cycle.js";
import { storyDrawn } from "./trips_map.js";

const KEYS = { locked: "live.mapLocked", nodata: "live.mapNoData", quiet: "live.mapQuiet" };

/** Show, retarget or hide the map's empty note for the current state. */
export function syncMapOverlay() {
  const pane = document.querySelector(".map-pane");
  if (!pane) return;
  let note = document.getElementById("map-empty");
  const show = !state.locked && state.status && state.markers.size === 0 && !storyDrawn();
  if (!show) {
    if (note) note.hidden = true;
    return;
  }
  if (!note) {
    note = document.createElement("div");
    note.id = "map-empty";
    note.className = "map-empty";
    note.setAttribute("aria-hidden", "true");
    pane.prepend(note);
  }
  note.dataset.kind = emptyKind(state.status);
  note.textContent = t(KEYS[note.dataset.kind]);
  note.hidden = false;
}

/** Lock purge: remove the note outright, nothing of the last view stays. */
export function purgeMapOverlay() {
  const note = document.getElementById("map-empty");
  if (note) note.remove();
}
