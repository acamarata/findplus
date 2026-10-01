/*
 * The Add place dialog's visible "where will this go" line (UAT #9).
 *
 * Purpose    : Saving a place with only a name used to drop it at the map centre
 *              with no word about where. This line always says where the place
 *              will be saved, with coordinates, and why.
 * Inputs     : The line's element, a kind ("centre", "current" or "picked") and
 *              the latitude and longitude.
 * Outputs    : Text on the element.
 * Constraints: Coordinates to 4 decimals (about 11 m), the same precision the
 *              locator's own "Location set" status uses.
 */
"use strict";

import { t, plural } from "./i18n.js";

/** Write the where-line for `kind` ("centre", "current" or "picked"). */
export function showWhere(el, kind, lat, lon) {
  if (!el) return;
  el.textContent = t(`places.where.${kind}`, {
    lat: Number(lat).toFixed(4),
    lon: Number(lon).toFixed(4),
  });
}

/** Clear the line (the dialog is closed or purged). */
export function clearWhere(el) {
  if (el) el.textContent = "";
}

/** Edit dialog: say how many alert rules use this place (0 hides the line). */
export function showUsage(el, ruleCount) {
  if (!el) return;
  el.hidden = !ruleCount;
  el.textContent = ruleCount ? plural("places.usage", ruleCount, { count: ruleCount }) : "";
}
