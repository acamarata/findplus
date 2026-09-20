/*
 * Per-device timeline lists, day navigation, export, and history deletion.
 *
 * Purpose    : Render the chronological, per-track observation list and load
 *              one day's data (map + list) for the selected device filter.
 * Constraints: Tracks are never merged — distance/elapsed-time are only
 *              meaningful within a single tracker's own points.
 */
"use strict";

import { $, state, fmtTime, fmtDateTime, fmtDuration, fmtDistance, todayLocal, showAlert, esc } from "./state.js";
import { api, postJson } from "./api.js";
import { renderMap, visiblePoints, deviceForTrack } from "./map.js";
import { renderBadge } from "./components/badge.js";
import { reload } from "./main.js";
import { providerWording } from "./devices.js";
import { t, plural } from "./i18n.js";

function statsHtml(stats) {
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

function timelineHtml(track) {
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
    }
    if (!point.is_movement && point.seconds_since_previous !== null) {
      meta.push(t("timeline.belowThreshold"));
    }

    html +=
      `<li class="tl-item${point.is_movement ? "" : " jitter"}" data-id="${point.id}">` +
      `<div><span class="tl-seq">${point.sequence}.</span> <span class="tl-time">${fmtTime(point.observed_at_local)}</span></div>` +
      `<div class="tl-coords">📍 ${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}</div>` +
      (meta.length ? `<div class="tl-meta">${esc(meta.join(" · "))}</div>` : "") +
      `</li>`;
  });
  return html + `</ol>`;
}

/**
 * The sticky header above one track: badge, name, observation count.
 *
 * The name prefers the device's label, so a track reads the way the user named
 * the tracker rather than the way the provider did.
 */
function trackHead(track) {
  const device = deviceForTrack(track);
  const head = document.createElement("div");
  head.className = "track-head";
  const swatch = document.createElement("span");
  swatch.className = "track-swatch";
  swatch.appendChild(
    renderBadge({
      icon: device.icon,
      color: device.color,
      label: device.label,
      name: device.name,
      size: 20,
    })
  );
  const name = document.createElement("span");
  name.className = "track-name";
  name.textContent = device.label || track.device_name || track.device_id;
  const count = document.createElement("span");
  count.className = "track-count";
  count.textContent = plural("timeline.observations", track.points.length, {
    n: track.points.length,
  });
  head.append(swatch, name, count);
  return head;
}

export function renderTracks() {
  const host = $("tracks");
  host.innerHTML = "";
  if (!state.timeline || !state.timeline.tracks.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = t("timeline.emptyDay");
    host.appendChild(empty);
    return;
  }

  state.timeline.tracks.forEach((track) => {
    const block = document.createElement("section");
    block.className = "track-block";
    block.appendChild(trackHead(track));
    // statsHtml()/timelineHtml() still return markup strings and carry no label
    // or icon data, so they are appended to the already-built head, not around it.
    block.insertAdjacentHTML("beforeend", statsHtml(track.stats) + timelineHtml(track));
    host.appendChild(block);
  });

  host.querySelectorAll(".tl-item").forEach((el) => {
    el.addEventListener("click", () => selectPoint(Number(el.dataset.id), true));
  });
  highlightSelection();
}

export function selectPoint(id, panTo) {
  state.selectedId = id;
  highlightSelection();
  const marker = state.markers.get(id);
  if (marker) {
    if (panTo) state.map.panTo(marker.getLatLng(), { animate: true });
    marker.openPopup();
  }
  const li = document.querySelector(`.tl-item[data-id="${id}"]`);
  if (li) li.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function highlightSelection() {
  document.querySelectorAll(".tl-item").forEach((el) => {
    el.classList.toggle("selected", el.dataset.id === String(state.selectedId));
  });
}

export async function loadDay(day) {
  state.day = day;
  $("day-picker").value = day;
  const params = new URLSearchParams({ day });
  if (state.deviceFilter) params.set("device_id", state.deviceFilter);
  try {
    state.timeline = await api(`/api/timeline?${params}`);
    state.selectedId = null;
    if (state.timeline.path_disclaimer) {
      $("path-disclaimer").textContent = state.timeline.path_disclaimer;
    }
    renderMap();
    renderTracks();
  } catch (err) {
    showAlert(t("timeline.loadFailed", { day, message: err.message }), "err");
  }
}

export function shiftDay(days) {
  const d = new Date(state.day + "T12:00:00");
  d.setDate(d.getDate() + days);
  loadDay(d.toISOString().slice(0, 10));
}

/** Build the export URL for the chosen format and scope, then navigate to it. */
function startExport() {
  const params = new URLSearchParams({ fmt: $("export-format").value });
  const scope = $("export-scope").value;
  if (scope === "day") params.set("day", state.day);
  if (scope === "range") {
    const start = $("range-start").value;
    const end = $("range-end").value;
    if (!start || !end) { showAlert(t("timeline.pickBothDates"), "warn"); return; }
    if (start > end) { showAlert(t("timeline.rangeStartAfterEnd"), "warn"); return; }
    params.set("start", start);
    params.set("end", end);
  }
  if (state.deviceFilter) params.set("device_id", state.deviceFilter);
  window.location.href = `/api/export?${params}`;
}

/** Wire day navigation, the movement-only toggle, export, and "jump to latest". */
export function wireTimelineControls() {
  $("day-picker").addEventListener("change", (e) => loadDay(e.target.value));
  $("btn-today").addEventListener("click", () => loadDay(todayLocal()));
  $("btn-prev-day").addEventListener("click", () => shiftDay(-1));
  $("btn-next-day").addEventListener("click", () => shiftDay(1));

  $("toggle-movement").addEventListener("change", (e) => {
    state.movementOnly = e.target.checked;
    renderMap();
    renderTracks();
  });

  $("export-scope").addEventListener("change", (e) => {
    $("range-inputs").classList.toggle("hidden", e.target.value !== "range");
    if (e.target.value === "range" && !$("range-start").value) {
      $("range-start").value = state.day;
      $("range-end").value = state.day;
    }
  });

  $("btn-export").addEventListener("click", startExport);

  $("btn-latest").addEventListener("click", async () => {
    try {
      const qs = state.deviceFilter ? `?device_id=${encodeURIComponent(state.deviceFilter)}` : "";
      const latest = await api(`/api/latest${qs}`);
      const day = latest.observed_at_local.slice(0, 10);
      if (day !== state.day) await loadDay(day);
      selectPoint(latest.id, true);
      showAlert(
        t("timeline.latestSummary", {
          device: latest.device_name,
          network: providerWording().network,
          observed: fmtDateTime(latest.observed_at_local),
          fetched: fmtDateTime(latest.fetched_at_local),
          age: fmtDuration(latest.age_seconds),
        }),
        "warn"
      );
    } catch (err) {
      showAlert(err.message, "warn");
    }
  });
}

/** Wire the delete-before-date and clear-all-history controls. */
export function wireHistoryControls() {
  $("btn-delete-before").addEventListener("click", async () => {
    const before = $("delete-before-date").value;
    if (!before) { showAlert(t("timeline.pickDateFirst"), "warn"); return; }
    try {
      const dry = await postJson("/api/history/delete-before", { before });
      if (!dry.would_delete) {
        $("delete-result").textContent = t("timeline.nothingOlderThan", { date: before });
        return;
      }
      if (!window.confirm(
        t("timeline.confirmDeleteBefore", { count: dry.would_delete, date: before })
      )) return;
      const done = await postJson("/api/history/delete-before", { before, confirm: true });
      $("delete-result").textContent = done.message;
      await reload();
    } catch (e) {
      showAlert(e.message, "err");
    }
  });

  $("btn-clear-all").addEventListener("click", async () => {
    try {
      const dry = await postJson("/api/history/clear", {});
      if (!dry.would_delete) {
        $("delete-result").textContent = t("timeline.noHistoryToClear");
        return;
      }
      if (!window.confirm(t("timeline.confirmClearAll", { count: dry.would_delete }))) return;
      const typed = window.prompt(t("timeline.promptTypeDelete"));
      if (typed !== "DELETE") { $("delete-result").textContent = t("timeline.deleteCancelled"); return; }
      const done = await postJson("/api/history/clear", { confirm: true });
      $("delete-result").textContent = done.message;
      await reload();
    } catch (e) {
      showAlert(e.message, "err");
    }
  });
}
