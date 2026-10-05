/*
 * The 1.2 dashboard body (#fp-day-host) that Latest and Activity borrow today.
 *
 * Purpose    : Until the Latest and Activity builders replace their adapters,
 *              both tabs show what the old Dashboard tab showed: the tracker
 *              blocks plus the Day story / Every sighting switch. That body
 *              exists once in the page (timeline.js, trips_view.js and
 *              track_blocks.js address it by id), so this module moves the one
 *              element between the two tab panels instead of copying it.
 * Inputs     : A tab container and which tab is asking.
 * Outputs    : #fp-day-host re-parented into the container; on Activity the
 *              host gets `fp-day-host--activity` (CSS hides the switch, the
 *              left-behind chips and the people banner) and the day view is
 *              forced to "every sighting".
 * Constraints: The Latest tab now only parks it for the tracker focus view
 *              (parkDayHost); DELETE this file when Activity stops using it. It never
 *              changes the remembered Day story / Every sighting choice.
 */
"use strict";

import { forceDayView } from "./trips_view.js";

/** Put the shared body in `container`; `activity` shows it as the raw feed. */
export function attachDayHost(container, { activity }) {
  const host = document.getElementById("fp-day-host");
  if (!host || !container) return;
  if (host.parentElement !== container) container.appendChild(host);
  host.classList.remove("fp-day-host--focus");
  host.classList.toggle("fp-day-host--activity", activity);
  forceDayView(activity ? "raw" : null);
}

/**
 * Park the body inside the Latest tab's focus view and impose "story" or "raw"
 * (Story | Sightings). `view` null releases it. The body's own switch, chips and
 * banner are hidden by `fp-day-host--focus`; the focus header has its own switch.
 */
export function parkDayHost(container, view) {
  const host = document.getElementById("fp-day-host");
  if (!host || !container) return;
  if (host.parentElement !== container) container.appendChild(host);
  host.classList.remove("fp-day-host--activity");
  host.classList.add("fp-day-host--focus");
  forceDayView(view);
}
