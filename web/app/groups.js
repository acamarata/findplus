/*
 * Groups tab: group selector, coloured member overlays, presence panel.
 *
 * Purpose    : Surface E5's group-presence engine — a selector picks a
 *              group, its non-stale members are drawn as coloured overlay
 *              circles, and a presence panel shows the verdict plus
 *              together/diverged/stale member lists and the group note.
 * Inputs     : GET /api/groups (cached for .color, which the presence
 *              endpoint does not carry); GET /api/groups/{id}/presence.
 * Outputs    : An overlay L.layerGroup; a legend; the #fp-presence-panel DOM;
 *              and (UAT U8) the map/timeline device filter while a group is
 *              picked, via state.groupFilter/groupMembers.
 * Constraints: Every element is built with createElement/textContent, never
 *              raw markup assignment. A generation counter discards a
 *              response from a superseded selectGroup() call (CR-C race).
 */
"use strict";

import { api } from "./api.js";
import { state } from "./state.js";
import { t } from "./i18n.js";
import { initDialog, purgeDialog } from "./groups_dialog.js";
import * as groupsList from "./groups_list.js";
import { renderMap } from "./map.js";
import { renderTracks } from "./timeline.js";
import {
  drawGroupOverlays, verdictLabel, verdictTitle, ageLabel, hasEverReported, nameList,
} from "./groups_presence_render.js";

let map = null;
let selectedGroupId = null;
let groupsById = new Map();
let overlayLayer = null;
let generation = 0;

/** groups_dialog.js's onSaved callback: loadGroups() alone refreshes the
 * selector and card grid, not the presence panel -- a stale-after edit left
 * it showing the pre-edit verdict/note until reselected or reloaded (UAT4
 * N31). Re-running selectGroup() for the still-selected id re-fetches it. */
async function onGroupSaved() {
  await loadGroups();
  if (selectedGroupId) await selectGroup(selectedGroupId);
}

export function init(mapArg, _deviceListEl) {
  map = mapArg;
  overlayLayer = L.layerGroup().addTo(map);
  initDialog(onGroupSaved);
  groupsList.init(document.getElementById("fp-groups-list")).catch(() => {});
  const select = document.getElementById("fp-group-select");
  if (select) {
    select.addEventListener("change", (e) => {
      if (e.target.value) selectGroup(e.target.value);
      else clearGroup();
    });
  }
  // UAT2 N12: main.js awaits refreshLockState() before calling init(), so
  // state.locked is already known here -- skip the fetch rather than fire it
  // and swallow a 401. lock.js's refreshTabsAfterUnlock() calls
  // refreshPresence() again once unlocked, which repopulates the selector.
  if (!state.locked) loadGroups().catch(() => {});
}

export async function loadGroups() {
  const groups = await api("/api/groups");
  groupsById = new Map(groups.map((g) => [String(g.id), g]));
  const select = document.getElementById("fp-group-select");
  if (!select) return;
  const current = select.value;
  while (select.firstChild) select.removeChild(select.firstChild);
  const allOpt = document.createElement("option");
  allOpt.value = "";
  allOpt.textContent = t("groups.allDevices");
  select.appendChild(allOpt);
  groups.forEach((g) => {
    const opt = document.createElement("option");
    opt.value = String(g.id);
    opt.textContent = g.name;
    select.appendChild(opt);
  });
  select.value = current;
  // One fetched list, two renderings: awaiting the cards here means a caller
  // awaiting loadGroups() sees the grid, the selector and the hint agree.
  await groupsList.loadCards();
  updateEmptyStateHint(groups.length);
}

/**
 * Show the "use the selector" hint only once there is a group to select.
 *
 * With zero groups the selector has nothing in it, so the hint would be
 * useless there; groups_list.js's own "groups.empty" paragraph (inside
 * #fp-groups-list) already carries the single empty-state message and
 * points at the Add group button, so the two never overlap (U12).
 */
function updateEmptyStateHint(groupCount) {
  const hint = document.getElementById("fp-groups-tab-hint");
  if (hint) hint.hidden = groupCount === 0;
}

/** Narrows the dashboard's map/timeline to `group`'s members (UAT U8). */
function applyGroupFilter(group) {
  state.groupFilter = String(group.id);
  state.groupMembers = new Set(group.members.map((m) => m.device_id));
  renderMap();
  renderTracks();
}

export async function selectGroup(id) {
  selectedGroupId = id;
  const group = groupsById.get(String(id));
  if (!group) return;
  applyGroupFilter(group);
  const myGeneration = ++generation;
  let presence;
  try {
    presence = await api(`/api/groups/${id}/presence?window=60`);
  } catch (_) {
    return;
  }
  if (myGeneration !== generation) return; // a later selectGroup() already won
  drawGroupOverlays(overlayLayer, presence, group);
  renderPresencePanel(presence);
}

/** Playwright's test_groups.py dynamic-imports this straight off groups.js,
 * so it stays defined here even though its helpers (verdictLabel/Title,
 * ageLabel, hasEverReported, nameList) moved to groups_presence_render.js. */
export function renderPresencePanel(presence) {
  const panel = document.getElementById("fp-presence-panel");
  if (!panel) return;
  while (panel.firstChild) panel.removeChild(panel.firstChild);

  const verdict = document.createElement("p");
  verdict.className = `fp-verdict fp-verdict--${presence.verdict}`;
  verdict.textContent = verdictLabel(presence);
  verdict.title = verdictTitle(presence);
  panel.appendChild(verdict);

  if (presence.note) {
    const note = document.createElement("p");
    note.className = "fp-group-note";
    note.textContent = presence.note;
    panel.appendChild(note);
  }

  // GroupPresence.together/diverged/stale hold member NAMES, not device ids
  // (groups/presence.py, pinned by tests/groups/test_presence.py). Looking them
  // up by device_id missed every time, so ageLabel() got undefined and every
  // stale row read "no fix for unknown" -- including after round 2 taught the
  // engine to keep the age (E1 honesty round 3 F2). Key on both, name first,
  // so this keeps working if the payload ever carries ids instead.
  const byId = new Map();
  presence.members.forEach((m) => {
    byId.set(m.name, m);
    byId.set(m.device_id, m);
  });
  panel.appendChild(nameList("fp-together-list", t("groups.verdictTogether"), presence.together, byId));
  panel.appendChild(nameList("fp-diverged-list", t("groups.listAway"), presence.diverged, byId));

  const staleList = document.createElement("ul");
  staleList.id = "fp-stale-list";
  presence.stale.forEach((key) => {
    const member = byId.get(key);
    const li = document.createElement("li");
    const badge = document.createElement("span");
    badge.className = "fp-stale-badge";
    const name = (member && member.name) || key;
    badge.textContent = hasEverReported(member) ? t("groups.staleBadge", { name, age: ageLabel(member) }) : t("groups.staleBadgeNoFix", { name });
    li.appendChild(badge);
    staleList.appendChild(li);
  });
  panel.appendChild(staleList);
}

export function clearGroup() {
  selectedGroupId = null;
  // Locking before the Groups tab was ever opened leaves overlayLayer null,
  // and an unguarded clearLayers() threw out of purgeRenderedData() — the one
  // path that must never throw (T0 wave-2 visual gate).
  if (overlayLayer) overlayLayer.clearLayers();
  const panel = document.getElementById("fp-presence-panel");
  if (panel) while (panel.firstChild) panel.removeChild(panel.firstChild);
  const legend = document.getElementById("fp-group-legend");
  if (legend) while (legend.firstChild) legend.removeChild(legend.firstChild);
  // "All devices" clears the U8 filter too (select, card click, or purge()).
  state.groupFilter = "";
  state.groupMembers = null;
  if (state.map) { renderMap(); renderTracks(); }
}

/** True when `id` is the panel's selected group (UAT4 N31: groups_list.js's
 * onDelete() checks this before clearing the panel). */
export function isGroupSelected(id) {
  return selectedGroupId != null && String(id) === String(selectedGroupId);
}

/** groups_list.js's card click uses this instead of selectGroup() directly,
 * so the `<select>` never keeps showing the group selected before. */
export function selectGroupById(id) {
  const select = document.getElementById("fp-group-select");
  if (select) select.value = String(id);
  selectGroup(id);
}

export async function refreshPresence() {
  if (selectedGroupId) await selectGroup(selectedGroupId);
  else await loadGroups();
}

/**
 * Destroy every member circle, the presence panel, the legend, the cached
 * group names, the group-select options, the add/edit dialog and the cards.
 *
 * Called from lock.js's purgeRenderedData() on every lock — `clearGroup()`
 * alone left `#fp-group-select`'s option list and the `groupsById` cache
 * behind, both real data surviving the lock (PROMPT.md §2). `generation`
 * also discards any in-flight `selectGroup()` response. lock.js imports only
 * this one function: the dialog and the card grid fan out from here.
 */
export function purge() {
  generation++;
  clearGroup();
  purgeDialog();
  groupsList.purgeCards();
  groupsById = new Map();
  const select = document.getElementById("fp-group-select");
  if (select) while (select.firstChild) select.removeChild(select.firstChild);
}
