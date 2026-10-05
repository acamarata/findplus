/*
 * "Fit to latest": the map control that replaced the top bar's Latest Location button.
 *
 * Purpose    : Jump to the most recent sighting (of the filtered tracker, or of
 *              all tracked ones), exactly as the old button did. The click
 *              handler is still timeline.js's wireHistoryControls() on
 *              #btn-latest; this module only draws the button inside the map.
 * Inputs     : The Leaflet map from initMap().
 * Outputs    : A top-right map control holding `#btn-latest` (crosshair icon,
 *              "Fit to latest"). status_view.js keeps disabling it while
 *              nothing is tracked; dashboard_empty.js still clicks it.
 * Constraints: Called right after initMap(), before the first await in main(),
 *              so the id exists when the click handlers are wired. The label
 *              carries `labelKey` for applyStaticI18n().
 */
"use strict";

import { button } from "./components/button.js";

export function addFitLatestControl(map) {
  const control = L.control({ position: "topright" });
  control.onAdd = () => {
    const box = L.DomUtil.create("div", "fp-map-control leaflet-control");
    box.appendChild(button({
      label: "Fit to latest", labelKey: "shell.fitLatest", titleKey: "shell.fitLatestTitle",
      icon: "crosshair", variant: "secondary", size: "sm", id: "btn-latest",
    }));
    L.DomEvent.disableClickPropagation(box);
    return box;
  };
  control.addTo(map);
  return control;
}
