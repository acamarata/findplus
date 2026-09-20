/*
 * Groups tab: group selector, coloured member overlays, presence panel.
 *
 * Purpose    : Surface E5's group-presence engine — a selector picks a
 *              group, its non-stale members are drawn as coloured overlay
 *              circles, and a presence panel shows the verdict plus
 *              together/diverged/stale member lists and the group note.
 * Inputs     : GET /api/groups (cached for .color, which the presence
 *              endpoint does not carry); GET /api/groups/{id}/presence.
 * Outputs    : An overlay L.layerGroup; a legend; the #fp-presence-panel DOM.
 * Constraints: Every element is built with createElement/textContent, never
 *              raw markup assignment. A generation counter discards a
 *              response from a superseded selectGroup() call (CR-C race).
 */
"use strict";

import { api } from "./api.js";

let map = null;
let selectedGroupId = null;
let groupsById = new Map();
let overlayLayer = null;
let generation = 0;

export function init(mapArg, _deviceListEl) {
  map = mapArg;
  overlayLayer = L.layerGroup().addTo(map);
  const select = document.getElementById("fp-group-select");
  if (select) {
    select.addEventListener("change", (e) => {
      if (e.target.value) selectGroup(e.target.value);
      else clearGroup();
    });
  }
  // Swallow a locked-boot 401 here (matches places.js:refreshAll) — the
  // lock screen already owns showing that state; a later loadGroups()/
  // refreshPresence() call after unlock repopulates the selector.
  loadGroups().catch(() => {});
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
  allOpt.textContent = "— All devices —";
  select.appendChild(allOpt);
  groups.forEach((g) => {
    const opt = document.createElement("option");
    opt.value = String(g.id);
    opt.textContent = g.name;
    select.appendChild(opt);
  });
  select.value = current;
}

export async function selectGroup(id) {
  selectedGroupId = id;
  const group = groupsById.get(String(id));
  if (!group) return;
  const myGeneration = ++generation;
  let presence;
  try {
    presence = await api(`/api/groups/${id}/presence?window=60`);
  } catch (_) {
    return;
  }
  if (myGeneration !== generation) return; // a later selectGroup() already won
  drawGroupOverlays(presence, group);
  renderPresencePanel(presence);
}

export function drawGroupOverlays(presence, group) {
  overlayLayer.clearLayers();
  const legend = document.getElementById("fp-group-legend");
  if (legend) while (legend.firstChild) legend.removeChild(legend.firstChild);
  presence.members.forEach((member) => {
    if (member.status === "stale") return;
    if (member.latitude == null || member.longitude == null) return;
    L.circle([member.latitude, member.longitude], {
      radius: 80, color: group.color, fillOpacity: 0.2, weight: 1,
    }).bindTooltip(member.name).addTo(overlayLayer);
    if (!legend) return;
    const item = document.createElement("span");
    item.className = "fp-legend-item";
    const swatch = document.createElement("span");
    swatch.className = "fp-legend-swatch";
    swatch.style.background = group.color;
    const label = document.createElement("span");
    label.textContent = member.name;
    item.append(swatch, label);
    legend.appendChild(item);
  });
}

/**
 * The one word a glance reads. It must never assert more than the engine found.
 *
 * `partial` covers two different situations. With names in `diverged` the tags
 * really are apart. With an empty `diverged` list it means only one member is
 * reporting and the rest are stale — presence.py:209 — and honesty.md's
 * presence_stale sentence forbids reading a missing fix as "not at home and not
 * left behind". Labelling that "Diverged" asserted exactly that inference,
 * while the note underneath it said the opposite.
 */
function verdictLabel(presence) {
  if (presence.verdict === "all_together") return "Together";
  if (presence.verdict !== "partial") return "Unknown";
  if (presence.diverged && presence.diverged.length > 0) return "Diverged";
  const reporting = presence.reporting_count;
  return reporting === 1 ? "Only 1 reporting" : "Unknown";
}

function ageLabel(member) {
  const minutes = member ? member.age_minutes : null;
  if (minutes == null) return "unknown";
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h`;
}

function nameList(id, deviceIds, byId) {
  const ul = document.createElement("ul");
  ul.id = id;
  deviceIds.forEach((deviceId) => {
    const li = document.createElement("li");
    li.textContent = (byId.get(deviceId) || {}).name || deviceId;
    ul.appendChild(li);
  });
  return ul;
}

export function renderPresencePanel(presence) {
  const panel = document.getElementById("fp-presence-panel");
  if (!panel) return;
  while (panel.firstChild) panel.removeChild(panel.firstChild);

  const verdict = document.createElement("p");
  verdict.className = `fp-verdict fp-verdict--${presence.verdict}`;
  verdict.textContent = verdictLabel(presence);
  panel.appendChild(verdict);

  if (presence.note) {
    const note = document.createElement("p");
    note.className = "fp-group-note";
    note.textContent = presence.note;
    panel.appendChild(note);
  }

  const byId = new Map(presence.members.map((m) => [m.device_id, m]));
  panel.appendChild(nameList("fp-together-list", presence.together, byId));
  panel.appendChild(nameList("fp-diverged-list", presence.diverged, byId));

  const staleList = document.createElement("ul");
  staleList.id = "fp-stale-list";
  presence.stale.forEach((deviceId) => {
    const member = byId.get(deviceId);
    const li = document.createElement("li");
    const badge = document.createElement("span");
    badge.className = "fp-stale-badge";
    const name = (member && member.name) || deviceId;
    badge.textContent = `${name} — no fix for ${ageLabel(member)}`;
    li.appendChild(badge);
    staleList.appendChild(li);
  });
  panel.appendChild(staleList);
}

export function clearGroup() {
  selectedGroupId = null;
  overlayLayer.clearLayers();
  const panel = document.getElementById("fp-presence-panel");
  if (panel) while (panel.firstChild) panel.removeChild(panel.firstChild);
  const legend = document.getElementById("fp-group-legend");
  if (legend) while (legend.firstChild) legend.removeChild(legend.firstChild);
}

export async function refreshPresence() {
  if (selectedGroupId) await selectGroup(selectedGroupId);
  else await loadGroups();
}

/**
 * Destroy every member circle, the presence panel, the legend, the cached
 * group names and the group-select options.
 *
 * Called from lock.js's purgeRenderedData() on every lock — `clearGroup()`
 * alone left `#fp-group-select`'s option list (group names) and the
 * `groupsById` cache behind, both real data surviving behind the lock
 * screen (PROMPT.md §2). Bumping `generation` also discards any in-flight
 * `selectGroup()` response that would otherwise repopulate the panel right
 * after this purge runs.
 */
export function purge() {
  generation++;
  clearGroup();
  groupsById = new Map();
  const select = document.getElementById("fp-group-select");
  if (select) while (select.firstChild) select.removeChild(select.firstChild);
}
