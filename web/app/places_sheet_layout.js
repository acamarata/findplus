/*
 * Place sheet: where it sits and how the map makes room for it.
 *
 * Purpose    : The add/edit place form is a non-modal sheet beside the live map
 *              (U5): a right-hand sheet over the side panel on a desktop, a
 *              bottom sheet under a shortened map on a phone. When the map is
 *              not on screen (the setup wizard moves it elsewhere, or a phone
 *              layout has it collapsed and cannot open it) the same form opens
 *              as a plain modal dialog and the map buttons are hidden.
 * Inputs     : The Leaflet `map` and the <dialog> element.
 * Outputs    : `data-sheet="1"|"0"` on the dialog; `fp-place-sheet-open` on
 *              <body> while a sheet is up (places-dialog.css reads both).
 * Constraints: Never touches a layout file; it only toggles those two hooks and
 *              asks Leaflet to re-measure.
 */
"use strict";

/** Open the collapsed card the map sits in on a phone (the 1.3 shell's #map-pane, or a <details>). */
function unfoldMap(map) {
  const card = map.getContainer().closest("details");
  if (card && !card.open) card.open = true;
  const pane = document.getElementById("map-pane");
  if (pane && !pane.classList.contains("is-open")) {
    pane.classList.add("is-open");
    document.getElementById("btn-map-toggle")?.setAttribute("aria-expanded", "true");
  }
}

/** True when the map is on the dashboard and visible, so the sheet can sit beside it. */
export function mapIsVisible(map) {
  const el = map.getContainer();
  if (el.closest("#setup-view")) return false;
  unfoldMap(map);
  const box = el.getBoundingClientRect();
  return box.width > 0 && box.height > 0;
}

function remeasure(map) {
  // The map's height changes with the body class on a phone; two passes cover the CSS transition.
  requestAnimationFrame(() => map.invalidateSize());
  setTimeout(() => map.invalidateSize(), 250);
}

/** Mark the page as having a sheet open and bring the map into view above it. */
export function enterSheet(map, dlg) {
  dlg.dataset.sheet = "1";
  document.body.classList.add("fp-place-sheet-open");
  map.getContainer().scrollIntoView({ block: "start" });
  remeasure(map);
}

/** Back to the normal layout (also the modal fallback's marker). */
export function leaveSheet(map, dlg) {
  dlg.dataset.sheet = "0";
  if (!document.body.classList.contains("fp-place-sheet-open")) return;
  document.body.classList.remove("fp-place-sheet-open");
  remeasure(map);
}
