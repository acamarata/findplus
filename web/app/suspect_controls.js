/*
 * The dashboard's "Show sightings that look wrong" box.
 *
 * Purpose    : A sighting the quality check flagged (a tag that jumps 2 km and back
 *              within two minutes) is drawn faintly, not hidden. This box turns
 *              those faint sightings off for people who would rather not see them.
 * Inputs     : state.timeline (each point may carry `suspect` and `suspect_reason`).
 * Outputs    : The box appears only on a day that has such sightings; changing it
 *              redraws the map and the list.
 * Constraints: On by default and remembered in this browser only (suspect_pref.js).
 */
"use strict";

import { $, state } from "./state.js";
import { renderMap } from "./map.js";
import { renderTracks } from "./track_blocks.js";
import { setShowSuspect, showSuspect } from "./suspect_pref.js";

/** Show the box only when the loaded day holds a sighting that looks wrong. */
export function syncSuspectToggle() {
  const tracks = (state.timeline && state.timeline.tracks) || [];
  $("suspect-group").hidden = !tracks.some((tr) => tr.points.some((p) => p.suspect));
  $("toggle-suspect").checked = showSuspect();
}

/** Wire the box once. */
export function wireSuspectToggle() {
  $("toggle-suspect").addEventListener("change", (e) => {
    setShowSuspect(e.target.checked);
    renderMap({ fit: false });
    renderTracks();
  });
}
