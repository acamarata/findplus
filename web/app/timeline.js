/*
 * Per-device timeline lists, day navigation, export, and history deletion.
 *
 * Purpose    : Render the chronological, per-track observation list and load
 *              one day's data (map + list) for the selected device filter.
 * Constraints: Tracks are never merged — distance/elapsed-time are only
 *              meaningful within a single tracker's own points.
 */
"use strict";

import { $, state, displayName, visibleTracks, fmtDateTime, fmtDuration, todayLocal, showAlert } from "./state.js";
import { api, postJson } from "./api.js";
import { renderMap, deviceForTrack } from "./map.js";
import { renderBadge } from "./components/badge.js";
import { reload } from "./main.js";
import { providerWording } from "./devices.js";
import { t, plural } from "./i18n.js";
import { nothingTrackedEmptyState, emptyDayState } from "./dashboard_empty.js";
import { confirmDialog } from "./components/confirm-dialog.js";
import { statsHtml, timelineHtml } from "./timeline_list.js";
import { paneError } from "./pane_error.js";

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
  name.textContent = displayName(device) || track.device_name || track.device_id;
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
  // The dashboard's group select narrows the timeline to one group's
  // members, matching the same filter renderMap() applies (UAT U8).
  const tracks = state.timeline ? visibleTracks(state.timeline.tracks) : [];
  if (!tracks.length) {
    // Nothing tracked at all is a different problem from a quiet day, and it
    // has a different answer: pick a device, or run setup again.
    const nothingTracked = !(state.devices || []).some((d) => d.is_tracked);
    if (nothingTracked) {
      host.appendChild(nothingTrackedEmptyState());
    } else {
      host.appendChild(emptyDayState());
    }
    return;
  }

  tracks.forEach((track) => {
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

/** What a loaded timeline is FOR: the day and the device filter it was fetched with. */
let loadedKey = null;
let loadSeq = 0;
const keyFor = (day, filter) => `${day}|${filter || ""}`;

/**
 * The pane after a failed load. A failure for a NEW selection (another day or
 * device) clears what was on screen, so the pane never shows device A's rows
 * under device B's name (UAT #1); a failed background refresh of the SAME
 * selection keeps its still-correct rows and only raises the banner.
 */
function showLoadError(day, err, key) {
  showAlert(t("timeline.loadFailed", { day, message: err.message }), "err");
  if (key === loadedKey || err.message === "Locked") return;
  state.timeline = null;
  state.selectedId = null;
  loadedKey = null;
  renderMap();
  const host = $("tracks");
  host.replaceChildren(
    paneError({ title: t("timeline.loadFailedTitle"), message: err.message, onRetry: () => loadDay(day) })
  );
}

export async function loadDay(day) {
  const lockGenAtFetch = state.lockGeneration; state.day = day; $("day-picker").value = day;
  const params = new URLSearchParams({ day });
  if (state.deviceFilter) params.set("device_id", state.deviceFilter);
  const key = keyFor(day, state.deviceFilter);
  const seq = ++loadSeq;
  try {
    const timeline = await api(`/api/timeline?${params}`);
    if (state.lockGeneration !== lockGenAtFetch) return; // locked mid-fetch: never render it
    // A newer loadDay() superseded this one while it was in flight.
    if (seq !== loadSeq) return;
    state.timeline = timeline;
    loadedKey = key;
    state.selectedId = null;
    if (state.timeline.path_disclaimer) {
      $("path-disclaimer").textContent = state.timeline.path_disclaimer;
    }
    renderMap();
    renderTracks();
  } catch (err) {
    if (state.lockGeneration !== lockGenAtFetch || seq !== loadSeq) return;
    showLoadError(day, err, key);
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
const confirmDelete = (body) => confirmDialog({ title: t("common.delete"), body, confirmLabel: t("common.delete"), danger: true }); // UAT6-N21
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
      if (!(await confirmDelete(t("timeline.confirmDeleteBefore", { count: dry.would_delete, date: before })))) return;
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
      if (!(await confirmDelete(t("timeline.confirmClearAll", { count: dry.would_delete })))) return;
      // window.prompt()'s "type DELETE" step is now confirmDialog()'s input.
      const confirmWord = t("timeline.confirmWord");
      const typed = await confirmDialog({ title: t("common.confirm"), body: "", confirmLabel: t("common.delete"), danger: true, input: { requireText: confirmWord, label: t("timeline.promptTypeDelete", { word: confirmWord }) } });
      if (!typed) { $("delete-result").textContent = t("timeline.deleteCancelled"); return; }
      const done = await postJson("/api/history/clear", { confirm: true });
      $("delete-result").textContent = done.message;
      await reload();
    } catch (e) {
      showAlert(e.message, "err");
    }
  });
}
