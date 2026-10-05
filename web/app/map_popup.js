/*
 * The popup a numbered map marker opens: tracker, time, place, accuracy, source.
 *
 * Purpose    : Split out of map.js to keep it under the 300-line cap.
 * Inputs     : One point of /api/timeline and the tracker's display name.
 * Outputs    : A markup string for Leaflet's bindPopup().
 * Constraints: Every dynamic value goes through esc() or a fmt*() helper.
 */
"use strict";

import { fmtTime, fmtDateTime, fmtDuration, fmtDistance, esc } from "./state.js";
import { t } from "./i18n.js";

export function popupHtml(point, deviceName, person = null) {
  // UAT2 N14: the tracker's name is the heading, not a subtitle under the
  // time -- a popup with several tracks open at once otherwise reads as a
  // bare timestamp with no way to tell whose fix it is.
  const rows = [
    `<b>${esc(deviceName)}</b>`,
    ...(person ? [`<div class="fp-popup-sub">${esc(t("personColours.popupOwner", { name: person.name }))}</div>`] : []),
    `<div class="fp-popup-sub">${fmtTime(point.observed_at_local)}</div>`,
    `<div>${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}</div>`,
  ];
  if (point.accuracy_meters != null) {
    const meters = Math.round(point.accuracy_meters);
    const rough = point.accuracy_meters >= 100;
    const text = rough ? t("map.popup.accuracyRough", { meters, rough: t("timeline.roughFix") }) : t("map.popup.accuracy", { meters });
    rows.push(`<div>${esc(text)}</div>`);
  } else {
    // Apple Find My never reports a metres figure (CF-P2-6): say so plainly
    // instead of just omitting the line, which could read as "exact".
    rows.push(`<div>${esc(t("timeline.accuracyUnknown"))}</div>`);
  }
  if (point.seconds_since_previous !== null) {
    rows.push(`<div>${esc(t("map.popup.sincePrevious", { duration: fmtDuration(point.seconds_since_previous) }))}</div>`);
  }
  const dist = fmtDistance(point.meters_from_previous);
  if (dist) rows.push(`<div>${esc(t("map.popup.fromPrevious", { distance: dist }))}</div>`);
  if (point.source) rows.push(`<div class="fp-popup-meta">${esc(t("map.popup.report", { source: point.source }))}</div>`);
  if (!point.is_movement && point.seconds_since_previous !== null) {
    rows.push(`<div class="fp-popup-meta">${esc(t("map.popup.belowThreshold"))}</div>`);
  }
  rows.push(`<div class="fp-popup-retrieved">${esc(t("map.popup.retrieved", { time: fmtDateTime(point.fetched_at) }))}</div>`);
  return rows.join("");
}
