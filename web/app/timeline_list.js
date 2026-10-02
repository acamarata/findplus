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

import { fmtTime, fmtDuration, fmtDistance, esc, todayLocal } from "./state.js";
import { visiblePoints } from "./map.js";
import { t } from "./i18n.js";
import { metersFromTrusted } from "./timeline_distance.js";

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

/** Hour headings appear once a list is long enough to need landmarks. */
const HOUR_HEADS_OVER = 10;
/** A fix this loose is called rough, not hidden behind a precise-looking number. */
const ROUGH_METERS = 100;

const hourLabel = (iso) => new Date(2000, 0, 1, Number(iso.slice(11, 13))).toLocaleTimeString([], { hour: "numeric" });

/** "5 min ago" for today's newest row only; older days read their own clock times. */
function agoHtml(point, isNewest) {
  if (!isNewest || String(point.observed_at_local).slice(0, 10) !== todayLocal()) return "";
  const secs = (Date.now() - Date.parse(point.observed_at)) / 1000;
  if (!(secs >= 0)) return "";
  return ` <span class="tl-ago">${esc(t("timeline.ago", { age: fmtDuration(secs) }))}</span>`;
}

/** The small grey line under a row: distance, accuracy (honestly), below-threshold. */
function metaParts(point, track) {
    const dist = fmtDistance(metersFromTrusted(track.points, point));
    const meta = [];
    if (dist) meta.push(t("timeline.fromPrevious", { distance: dist }));
    if (point.accuracy_meters != null) {
      meta.push(t("timeline.accuracy", { meters: Math.round(point.accuracy_meters) }));
      if (point.accuracy_meters >= ROUGH_METERS) meta.push(t("timeline.roughFix"));
    } else {
      // Apple Find My never reports a metres figure (CF-P2-6): say so plainly
      // instead of just omitting the line, which could read as "exact".
      meta.push(t("timeline.accuracyUnknown"));
    }
    if (!point.is_movement && point.seconds_since_previous !== null) {
      meta.push(t("timeline.belowThreshold"));
    }
  return meta;
}

export function timelineHtml(track) {
  const points = visiblePoints(track);
  if (!points.length) {
    return `<div class="empty">${esc(t("timeline.emptyDay"))}</div>`;
  }
  let html = `<ol class="timeline">`;
  let hour = "";
  points.forEach((point, index) => {
    if (points.length > HOUR_HEADS_OVER && point.observed_at_local.slice(0, 13) !== hour) {
      hour = point.observed_at_local.slice(0, 13);
      html += `<li class="tl-hour" aria-hidden="true">${esc(hourLabel(point.observed_at_local))}</li>`;
    }
    if (point.gap_before && point.seconds_since_previous) {
      const gap = t("timeline.noDetectionsFor", {
        duration: fmtDuration(point.seconds_since_previous).toUpperCase(),
      });
      html += `<li class="tl-gap">${esc(gap)}</li>`;
    }
    const meta = metaParts(point, track);

    // Coordinates stay in the title attribute for hover even when a place name
    // is shown in their place (U30b) — the API resolves place_name server-side
    // (routes_history.py::_annotate_place_names) against every saved place.
    // UAT6-N30: the sprite's map pin, not an emoji that renders per-OS.
    const coordsTitle = `${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}`;
    const coordsLine = point.place_name
      ? `<div class="tl-coords" title="${esc(coordsTitle)}">${PIN_ICON}${esc(point.place_name)}</div>`
      : `<div class="tl-coords">${PIN_ICON}${esc(coordsTitle)}</div>`;

    html +=
      `<li class="tl-item${point.is_movement ? "" : " jitter"}${point.suspect ? " is-suspect" : ""}" data-id="${point.id}">` +
      `<div><span class="tl-seq">${point.sequence}.</span> <span class="tl-time">${fmtTime(point.observed_at_local)}</span>${agoHtml(point, index === points.length - 1)}</div>` +
      coordsLine +
      (meta.length ? `<div class="tl-meta">${esc(meta.join(" · "))}</div>` : "") +
      (point.suspect ? `<div class="tl-suspect">${esc(point.suspect_reason || t("person.map.suspectTip"))}</div>` : "") +
      `</li>`;
  });
  return html + `</ol>`;
}
