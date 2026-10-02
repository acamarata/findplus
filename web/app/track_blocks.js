/*
 * The timeline pane's per-tracker blocks: head, collapse, and the rows below.
 *
 * Purpose    : With 17 trackers the pane was one 7000 px column. Each tracker
 *              is now a block with a head that folds its stats and rows away.
 *              Up to FOLD_OVER trackers every block starts open; beyond that
 *              only the first does, and the rest show a one-line summary.
 * Inputs     : state.timeline, state.devices, state.selectedId.
 * Outputs    : The #tracks DOM, plus expandFor(id) for map-to-list selection.
 * Constraints: Tracks are never merged. A user's own open/closed choice
 *              survives a refresh (openState); rows inside a folded block are
 *              hidden, so the keyboard group skips them.
 */
"use strict";

import { $, state, visibleTracks, fmtTime } from "./state.js";
import { deviceForTrack } from "./map.js";
import { selectPoint } from "./timeline.js";
import { renderBadge } from "./components/badge.js";
import { plural, t } from "./i18n.js";
import { nothingTrackedEmptyState, emptyDayState } from "./dashboard_empty.js";
import { statsHtml, timelineHtml } from "./timeline_list.js";
import { uniqueLabel } from "./device_label.js";
import { syncRoving } from "./timeline_keys.js";
import { renderStoryPane } from "./trips_view.js";

/** More trackers than this and only the first block starts open. */
export const FOLD_OVER = 3;

/** device_id -> true (open) / false (folded), set by the user's own clicks. */
const openState = new Map();

const isOpen = (track, index, total) =>
  openState.has(track.device_id) ? openState.get(track.device_id) : total <= FOLD_OVER || index === 0;

/** Forget every remembered choice (lock purge, device-set change). */
export function resetTrackOpenState() {
  openState.clear();
}

function headLabel(track) {
  const device = deviceForTrack(track);
  const swatch = document.createElement("span");
  swatch.className = "track-swatch";
  swatch.appendChild(
    renderBadge({ icon: device.icon, color: device.color, label: device.label, name: device.name, size: 20 })
  );
  const name = document.createElement("span");
  name.className = "track-name";
  name.textContent = uniqueLabel(device) || track.device_name || track.device_id;
  const count = document.createElement("span");
  count.className = "track-count";
  const n = track.points.length;
  const last = track.points[n - 1];
  count.textContent = plural("timeline.observations", n, { n }) + (last ? ` · ${t("timeline.lastAt", { time: fmtTime(last.observed_at_local) })}` : "");
  return [swatch, name, count];
}

/** The head: a real button, so the whole row folds and unfolds by keyboard too. */
function trackHead(track, bodyId, open) {
  const head = document.createElement("div");
  head.className = "track-head";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "track-toggle";
  toggle.setAttribute("aria-expanded", String(open));
  toggle.setAttribute("aria-controls", bodyId);
  const chevron = document.createElement("span");
  chevron.className = "track-chevron";
  chevron.setAttribute("aria-hidden", "true");
  toggle.append(chevron, ...headLabel(track));
  head.appendChild(toggle);
  return head;
}

function setOpen(block, open) {
  block.querySelector(".track-toggle").setAttribute("aria-expanded", String(open));
  block.querySelector(".track-body").hidden = !open;
  block.classList.toggle("is-folded", !open);
}

/** Open the block holding point `id` so a map click can reveal its row. */
export function expandFor(id) {
  const li = document.querySelector(`.tl-item[data-id="${id}"]`);
  const block = li && li.closest(".track-block");
  if (!block || !block.classList.contains("is-folded")) return;
  openState.set(block.dataset.deviceId, true);
  setOpen(block, true);
  syncRoving($("tracks"));
}

function buildBlock(track, index, total) {
  const open = isOpen(track, index, total);
  const block = document.createElement("section");
  block.className = "track-block";
  block.dataset.deviceId = track.device_id;
  const bodyId = `track-body-${index}`;
  block.appendChild(trackHead(track, bodyId, open));
  const body = document.createElement("div");
  body.className = "track-body";
  body.id = bodyId;
  // statsHtml()/timelineHtml() return markup strings (every value escaped there).
  body.insertAdjacentHTML("beforeend", statsHtml(track.stats) + timelineHtml(track));
  block.appendChild(body);
  setOpen(block, open);
  block.querySelector(".track-toggle").addEventListener("click", () => {
    const next = block.classList.contains("is-folded");
    openState.set(track.device_id, next);
    setOpen(block, next);
    syncRoving($("tracks"));
  });
  return block;
}

/** "Show all / Hide all" row, only worth having when blocks are folded away. */
function foldAllRow(host) {
  const row = document.createElement("div");
  row.className = "track-foldall";
  for (const [key, open] of [["timeline.expandAll", true], ["timeline.collapseAll", false]]) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-tiny btn-secondary";
    btn.textContent = t(key);
    btn.addEventListener("click", () => {
      host.querySelectorAll(".track-block").forEach((b) => { openState.set(b.dataset.deviceId, open); setOpen(b, open); });
      syncRoving(host);
    });
    row.appendChild(btn);
  }
  return row;
}

export function highlightSelection() {
  document.querySelectorAll(".tl-item").forEach((el) => {
    el.classList.toggle("selected", el.dataset.id === String(state.selectedId));
  });
}

export function renderTracks() {
  const host = $("tracks");
  host.innerHTML = "";
  // The day story (trips_view.js) takes the pane over when it is the chosen view.
  if (renderStoryPane()) return;
  // The dashboard's group select narrows the timeline to one group's members,
  // matching the same filter renderMap() applies (UAT U8).
  const tracks = state.timeline ? visibleTracks(state.timeline.tracks) : [];
  if (!tracks.length) {
    // Nothing tracked at all is a different problem from a quiet day.
    const nothingTracked = !(state.devices || []).some((d) => d.is_tracked);
    host.appendChild(nothingTracked ? nothingTrackedEmptyState() : emptyDayState());
    return;
  }
  if (tracks.length > FOLD_OVER) host.appendChild(foldAllRow(host));
  tracks.forEach((track, i) => host.appendChild(buildBlock(track, i, tracks.length)));
  host.querySelectorAll(".tl-item").forEach((el) => {
    el.addEventListener("click", () => selectPoint(Number(el.dataset.id), true));
  });
  highlightSelection();
  syncRoving(host);
}
