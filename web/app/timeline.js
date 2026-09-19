/*
 * Per-device timeline lists, day navigation, export, and history deletion.
 *
 * Purpose    : Render the chronological, per-track observation list and load
 *              one day's data (map + list) for the selected device filter.
 * Constraints: Tracks are never merged — distance/elapsed-time are only
 *              meaningful within a single tracker's own points.
 */
"use strict";

import { $, state, fmtTime, fmtDateTime, fmtDuration, fmtDistance, todayLocal, colorFor, showAlert } from "./state.js";
import { api, postJson } from "./api.js";
import { renderMap, visiblePoints } from "./map.js";
import { reload } from "./main.js";

function statsHtml(stats) {
  if (!stats || !stats.observation_count) return "";
  const cells = [
    ["First observation", fmtTime(stats.first_observed_at_local)],
    ["Last observation", fmtTime(stats.last_observed_at_local)],
    ["Unique observations", String(stats.observation_count)],
    ["Meaningful movements", String(stats.movement_count)],
    ["Approx. distance", `${stats.approximate_distance_miles.toFixed(2)} mi`],
    ["Longest gap", fmtDuration(stats.longest_gap_seconds)],
    ["Time span covered", fmtDuration(stats.time_span_seconds)],
  ];
  return `<div class="stats">` +
    cells.map(([l, v]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("") +
    `<div class="stat-note">${stats.distance_label} — not the distance actually travelled.</div>` +
    `</div>`;
}

function timelineHtml(track) {
  const points = visiblePoints(track);
  if (!points.length) {
    return `<div class="empty">No observations recorded for this day.</div>`;
  }
  let html = `<ol class="timeline">`;
  points.forEach((point) => {
    if (point.gap_before && point.seconds_since_previous) {
      html += `<li class="tl-gap">NO NEW DETECTIONS FOR ${fmtDuration(point.seconds_since_previous).toUpperCase()}</li>`;
    }
    const dist = fmtDistance(point.meters_from_previous);
    const meta = [];
    if (dist) meta.push(`${dist} from previous observation`);
    if (point.accuracy_meters != null) meta.push(`±${Math.round(point.accuracy_meters)} m`);
    if (!point.is_movement && point.seconds_since_previous !== null) meta.push("below movement threshold");

    html +=
      `<li class="tl-item${point.is_movement ? "" : " jitter"}" data-id="${point.id}">` +
      `<div><span class="tl-seq">${point.sequence}.</span> <span class="tl-time">${fmtTime(point.observed_at_local)}</span></div>` +
      `<div class="tl-coords">📍 ${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}</div>` +
      (meta.length ? `<div class="tl-meta">${meta.join(" · ")}</div>` : "") +
      `</li>`;
  });
  return html + `</ol>`;
}

export function renderTracks() {
  const host = $("tracks");
  host.innerHTML = "";
  if (!state.timeline || !state.timeline.tracks.length) {
    host.innerHTML = `<div class="empty">No observations recorded for this day.</div>`;
    return;
  }

  state.timeline.tracks.forEach((track) => {
    const block = document.createElement("section");
    block.className = "track-block";
    block.innerHTML =
      `<div class="track-head">` +
      `<span class="track-swatch" style="background:${colorFor(track.device_id)}"></span>` +
      `<span class="track-name">${track.device_name || track.device_id}</span>` +
      `<span class="track-count">${track.points.length} observation${track.points.length === 1 ? "" : "s"}</span>` +
      `</div>` +
      statsHtml(track.stats) +
      timelineHtml(track);
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
    showAlert(`Could not load ${day}: ${err.message}`, "err");
  }
}

export function shiftDay(days) {
  const d = new Date(state.day + "T12:00:00");
  d.setDate(d.getDate() + days);
  loadDay(d.toISOString().slice(0, 10));
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

  $("btn-export").addEventListener("click", () => {
    const params = new URLSearchParams({ fmt: $("export-format").value });
    const scope = $("export-scope").value;
    if (scope === "day") params.set("day", state.day);
    if (scope === "range") {
      const start = $("range-start").value;
      const end = $("range-end").value;
      if (!start || !end) { showAlert("Pick both a start and an end date.", "warn"); return; }
      if (start > end) { showAlert("The range start is after its end.", "warn"); return; }
      params.set("start", start);
      params.set("end", end);
    }
    if (state.deviceFilter) params.set("device_id", state.deviceFilter);
    window.location.href = `/api/export?${params}`;
  });

  $("btn-latest").addEventListener("click", async () => {
    try {
      const qs = state.deviceFilter ? `?device_id=${encodeURIComponent(state.deviceFilter)}` : "";
      const latest = await api(`/api/latest${qs}`);
      const day = latest.observed_at_local.slice(0, 10);
      if (day !== state.day) await loadDay(day);
      selectPoint(latest.id, true);
      showAlert(
        `${latest.device_name} — last observed by Find Hub ${fmtDateTime(latest.observed_at_local)} · ` +
        `retrieved ${fmtDateTime(latest.fetched_at_local)} · age ${fmtDuration(latest.age_seconds)}`,
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
    if (!before) { showAlert("Pick a date first.", "warn"); return; }
    try {
      const dry = await postJson("/api/history/delete-before", { before });
      if (!dry.would_delete) {
        $("delete-result").textContent = `Nothing is older than ${before}.`;
        return;
      }
      if (!window.confirm(
        `Permanently delete ${dry.would_delete} observation(s) recorded before ${before}?\n\n` +
        `This cannot be undone.`
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
        $("delete-result").textContent = "There is no history to clear.";
        return;
      }
      if (!window.confirm(
        `Delete ALL ${dry.would_delete} observation(s) for every device?\n\n` +
        `This erases the entire location history and cannot be undone.`
      )) return;
      const typed = window.prompt('Type DELETE to confirm erasing all history:');
      if (typed !== "DELETE") { $("delete-result").textContent = "Cancelled — nothing deleted."; return; }
      const done = await postJson("/api/history/clear", { confirm: true });
      $("delete-result").textContent = done.message;
      await reload();
    } catch (e) {
      showAlert(e.message, "err");
    }
  });
}
