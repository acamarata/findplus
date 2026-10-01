/*
 * Map helpers: tile-failure note, many-points decluttering, device legend.
 *
 * Purpose    : Keep map.js small. With 17 trackers the map needs a key (which
 *              colour is whose), a calmer look when hundreds of points share a
 *              screen, and an honest message when the tiles cannot load.
 * Inputs     : The Leaflet map and tile layer, and the tracks map.js drew.
 * Outputs    : A legend control, the `map--dense` class on #map, #map-tiles-note.
 * Constraints: Leaflet is the global `L`. Legend rows are plain buttons built
 *              with textContent; they only move the view, never the data.
 */
"use strict";

import { t } from "./i18n.js";

/** More drawn points than this and the middle markers shrink to dots. */
export const DENSE_OVER = 60;
/** Zoomed in at least this far, every marker shows its number again. */
export const DENSE_UNTIL_ZOOM = 15;
/** Failed tiles (with none loaded) before the offline note appears. */
const TILE_ERRORS_BEFORE_NOTE = 3;

/** Show a calm note when the base-map tiles cannot be fetched (offline, blocked). */
export function watchTiles(layer, pane) {
  let errors = 0;
  let note = null;
  const hide = () => { if (note) note.hidden = true; };
  layer.on("tileload", () => { errors = 0; hide(); });
  layer.on("tileerror", () => {
    errors += 1;
    if (errors < TILE_ERRORS_BEFORE_NOTE) return;
    if (!note) {
      note = document.createElement("div");
      note.id = "map-tiles-note";
      note.className = "map-note";
      note.setAttribute("role", "status");
      note.textContent = t("map.tilesFailed");
      pane.appendChild(note);
    }
    note.hidden = false;
  });
}

/** Toggle the dense look for the current point count and zoom. */
export function syncDense(map, total) {
  const el = map.getContainer();
  el.classList.toggle("map--dense", total > DENSE_OVER && map.getZoom() < DENSE_UNTIL_ZOOM);
}

/** One row per tracker: its colour, name and point count; a click frames its path. */
export function renderLegend(map, entries, previous) {
  if (previous) previous.remove();
  if (entries.length < 2) return null;
  const control = L.control({ position: "bottomleft" });
  control.onAdd = () => {
    const box = L.DomUtil.create("div", "map-legend");
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", t("map.legendLabel"));
    entries.forEach(({ name, color, latlngs }) => {
      const row = document.createElement("button");
      row.type = "button";
      const dot = document.createElement("span");
      dot.className = "lg-dot";
      dot.style.setProperty("background", color);
      const label = document.createElement("span");
      label.className = "lg-name";
      label.textContent = name;
      row.append(dot, label);
      row.title = t("map.legendFrame", { name });
      row.addEventListener("click", () => map.fitBounds(L.latLngBounds(latlngs), { padding: [42, 42], maxZoom: 17 }));
      box.appendChild(row);
    });
    L.DomEvent.disableClickPropagation(box);
    L.DomEvent.disableScrollPropagation(box);
    return box;
  };
  return control.addTo(map);
}
