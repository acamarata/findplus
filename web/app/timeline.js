/*
 * Per-device timeline lists, day navigation, export, and history deletion.
 *
 * Purpose    : Render the chronological, per-track observation list and load
 *              one day's data (map + list) for the selected device filter.
 * Constraints: Tracks are never merged — distance/elapsed-time are only
 *              meaningful within a single tracker's own points.
 */
"use strict";

import { wireExportPopover } from "./export_popover.js";
import { $, state, fmtDateTime, fmtDuration, todayLocal, showAlert } from "./state.js";
import { api, postJson } from "./api.js";
import { renderMap } from "./map.js";
import { reload } from "./main.js";
import { providerWording } from "./devices.js";
import { t } from "./i18n.js";
import { confirmDialog } from "./components/confirm-dialog.js";
import { expandFor, highlightSelection, renderTracks } from "./track_blocks.js";
import { paneError } from "./pane_error.js";
import { syncSuspectToggle, wireSuspectToggle } from "./suspect_controls.js";
import { wireTimelineKeys } from "./timeline_keys.js";
import { hideStory, wireStory } from "./trips_view.js";

export { renderTracks };

export function selectPoint(id, panTo) {
  state.selectedId = id;
  expandFor(id);
  highlightSelection();
  const marker = state.markers.get(id);
  if (marker) {
    if (panTo) state.map.panTo(marker.getLatLng(), { animate: true });
    marker.openPopup();
  }
  const li = document.querySelector(`.tl-item[data-id="${id}"]`);
  if (li) li.scrollIntoView({ block: "nearest", behavior: "smooth" });
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
  showAlert(t("timeline.loadFailed", { day, message: err.message }), "err", {
    action: { label: t("common.retry"), run: () => loadDay(day) },
  });
  if (key === loadedKey || err.message === "Locked") return;
  state.timeline = null;
  state.selectedId = null;
  hideStory();
  loadedKey = null;
  loadedJson = "";
  renderMap();
  const host = $("tracks");
  host.replaceChildren(
    paneError({ title: t("timeline.loadFailedTitle"), message: err.message, onRetry: () => loadDay(day) })
  );
  window.dispatchEvent(new CustomEvent("findplus:tracks-rendered"));
}

/** The pane while a NEW selection loads, so it is never blank (UAT #13). */
function showPaneLoading(seq) {
  if (seq !== loadSeq) return;
  // Grey placeholder rows, not a bare word: the pane keeps its shape while it waits.
  const note = document.createElement("div");
  note.className = "skeleton";
  note.setAttribute("role", "status");
  note.setAttribute("aria-label", t("common.loading"));
  for (let i = 0; i < 7; i += 1) note.appendChild(document.createElement("i"));
  hideStory();
  $("tracks").replaceChildren(note);
}

/** JSON of the timeline on screen, so an identical refresh redraws nothing. */
let loadedJson = "";

/**
 * Put a fetched timeline on screen.
 *
 * A refresh of the SAME day and device (the live timer, a poll finishing) is
 * not a new view: identical data redraws nothing (no flicker, no map jump),
 * and changed data keeps the selected row, the pane's scroll position and the
 * map's own zoom and pan. Only a new selection resets those.
 */
function applyTimeline(timeline, key) {
  // Labels, icons and colours are drawn from the device list, so they count too.
  const looks = (state.devices || []).map((d) => [d.device_id, d.name, d.label, d.icon, d.color]);
  const json = JSON.stringify([timeline, looks]);
  const refresh = key === loadedKey && state.timeline && state.markers.size > 0;
  if (refresh && json === loadedJson) return;
  const pane = $("tracks").closest(".timeline-pane");
  const scroll = refresh && pane ? pane.scrollTop : 0;
  const kept = refresh ? state.selectedId : null;
  state.timeline = timeline;
  syncSuspectToggle();
  loadedKey = key;
  loadedJson = json;
  state.selectedId = null;
  if (timeline.path_disclaimer) $("path-disclaimer").textContent = timeline.path_disclaimer;
  renderMap({ fit: !refresh });
  if (kept !== null && state.markers.has(kept)) state.selectedId = kept;
  renderTracks();
  if (pane) pane.scrollTop = scroll;
}

export async function loadDay(day) {
  const lockGenAtFetch = state.lockGeneration; state.day = day; $("day-picker").value = day;
  const params = new URLSearchParams({ day });
  if (state.deviceFilter) params.set("device_id", state.deviceFilter);
  const key = keyFor(day, state.deviceFilter);
  const seq = ++loadSeq;
  // Only a selection that is not on screen yet gets the notice, and only when
  // the answer is slow, so a quick day change does not flash it.
  const slow = key === loadedKey ? null : setTimeout(() => showPaneLoading(seq), 250);
  try {
    const timeline = await api(`/api/timeline?${params}`);
    if (state.lockGeneration !== lockGenAtFetch) return; // locked mid-fetch: never render it
    // A newer loadDay() superseded this one while it was in flight.
    if (seq !== loadSeq) return;
    applyTimeline(timeline, key);
  } catch (err) {
    if (state.lockGeneration !== lockGenAtFetch || seq !== loadSeq) return;
    showLoadError(day, err, key);
  } finally {
    clearTimeout(slow);
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
  wireTimelineKeys($("tracks"), (id) => selectPoint(id, true));
  wireStory();
  wireSuspectToggle();
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
  wireExportPopover();

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
/**
 * One line under the Delete history buttons, inside the Settings dialog.
 *
 * A message sent to the page banner sits behind the dialog's backdrop, so an
 * empty date or a failed delete looked like a button that did nothing (UAT #16).
 */
function showDeleteResult(message, kind = "warn") {
  const el = $("delete-result");
  el.textContent = message;
  el.className = kind === "err" ? "fp-dialog-error" : "modal-rate";
}

/** Wire the delete-before-date and clear-all-history controls. */
export function wireHistoryControls() {
  $("btn-delete-before").addEventListener("click", async () => {
    const before = $("delete-before-date").value;
    if (!before) { showDeleteResult(t("timeline.pickDateFirst")); return; }
    try {
      const dry = await postJson("/api/history/delete-before", { before });
      if (!dry.would_delete) {
        showDeleteResult(t("timeline.nothingOlderThan", { date: before }));
        return;
      }
      if (!(await confirmDelete(t("timeline.confirmDeleteBefore", { count: dry.would_delete, date: before })))) return;
      const done = await postJson("/api/history/delete-before", { before, confirm: true });
      showDeleteResult(done.message);
      await reload();
    } catch (e) {
      showDeleteResult(e.message, "err");
    }
  });

  $("btn-clear-all").addEventListener("click", async () => {
    try {
      const dry = await postJson("/api/history/clear", {});
      if (!dry.would_delete) {
        showDeleteResult(t("timeline.noHistoryToClear"));
        return;
      }
      if (!(await confirmDelete(t("timeline.confirmClearAll", { count: dry.would_delete })))) return;
      // window.prompt()'s "type DELETE" step is now confirmDialog()'s input.
      const confirmWord = t("timeline.confirmWord");
      const typed = await confirmDialog({ title: t("common.confirm"), body: "", confirmLabel: t("common.delete"), danger: true, input: { requireText: confirmWord, label: t("timeline.promptTypeDelete", { word: confirmWord }) } });
      if (!typed) { showDeleteResult(t("timeline.deleteCancelled")); return; }
      const done = await postJson("/api/history/clear", { confirm: true });
      showDeleteResult(done.message);
      await reload();
    } catch (e) {
      showDeleteResult(e.message, "err");
    }
  });
}
