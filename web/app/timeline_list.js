/*
 * Timeline markup: the per-track stats strip and the chronological point list.
 *
 * Purpose    : Build the HTML for one track's stats and observation rows. Split
 *              out of timeline.js to stay under the 300-line file cap.
 * Inputs     : One track object from /api/timeline (stats and points).
 * Outputs    : Markup strings, which timeline.js inserts into the track block.
 * Constraints: Every dynamic value goes through esc() or fmt*(). Rows are plain
 *              <li> elements; timeline.js wires their click handlers.
 */
"use strict";

import { fmtTime, fmtDuration, fmtDistance, esc } from "./state.js";
import { visiblePoints } from "./map.js";
import { t } from "./i18n.js";

const PIN_ICON = `<svg class="tl-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#lucide-map-pin"></use></svg>`;

export function statsHtml(stats) {
  if (!stats || !stats.observation_count) return "";
  const cells = [
    [t("timeline.statFirst"), fmtTime(stats.first_observed_at_local)],
    [t("timeline.statLast"), fmtTime(stats.last_observed_at_local)],
    [t("timeline.statUnique"), String(stats.observation_count)],
    [t("timeline.statMovements"), String(stats.movement_count)],
    [t("timeline.statDistance"), t("timeline.distanceMiles", { miles: stats.approximate_distance_miles.toFixed(2) })],
    [t("timeline.statLongestGap"), fmtDuration(stats.longest_gap_seconds)],
    [t("timeline.statTimeSpan"), fmtDuration(stats.time_span_seconds)],
  ];
  return `<div class="stats">` +
    cells.map(([l, v]) => `<div class="stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("") +
    `<div class="stat-note">${esc(t("timeline.statNote", { label: stats.distance_label }))}</div>` +
    `</div>`;
}

export function timelineHtml(track) {
  const points = visiblePoints(track);
  if (!points.length) {
    return `<div class="empty">${esc(t("timeline.emptyDay"))}</div>`;
  }
  let html = `<ol class="timeline">`;
  points.forEach((point) => {
    if (point.gap_before && point.seconds_since_previous) {
      const gap = t("timeline.noDetectionsFor", {
        duration: fmtDuration(point.seconds_since_previous).toUpperCase(),
      });
      html += `<li class="tl-gap">${esc(gap)}</li>`;
    }
    const dist = fmtDistance(point.meters_from_previous);
    const meta = [];
    if (dist) meta.push(t("timeline.fromPrevious", { distance: dist }));
    if (point.accuracy_meters != null) {
      meta.push(t("timeline.accuracy", { meters: Math.round(point.accuracy_meters) }));
    } else {
      // Apple Find My never reports a metres figure (CF-P2-6): say so plainly
      // instead of just omitting the line, which could read as "exact".
      meta.push(t("timeline.accuracyUnknown"));
    }
    if (!point.is_movement && point.seconds_since_previous !== null) {
      meta.push(t("timeline.belowThreshold"));
    }

    // Coordinates stay in the title attribute for hover even when a place name
    // is shown in their place (U30b) — the API resolves place_name server-side
    // (routes_history.py::_annotate_place_names) against every saved place.
    // UAT6-N30: the sprite's map pin, not an emoji that renders per-OS.
    const coordsTitle = `${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}`;
    const coordsLine = point.place_name
      ? `<div class="tl-coords" title="${esc(coordsTitle)}">${PIN_ICON}${esc(point.place_name)}</div>`
      : `<div class="tl-coords">${PIN_ICON}${esc(coordsTitle)}</div>`;

    html +=
      `<li class="tl-item${point.is_movement ? "" : " jitter"}" data-id="${point.id}">` +
      `<div><span class="tl-seq">${point.sequence}.</span> <span class="tl-time">${fmtTime(point.observed_at_local)}</span></div>` +
      coordsLine +
      (meta.length ? `<div class="tl-meta">${esc(meta.join(" · "))}</div>` : "") +
      `</li>`;
  });
  return html + `</ol>`;
}
