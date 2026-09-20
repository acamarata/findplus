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
import { esc, fmtAgeMinutes } from "./state.js";
import { t } from "./i18n.js";
import { initDialog, purgeDialog } from "./groups_dialog.js";
import * as groupsList from "./groups_list.js";

let map = null;
let selectedGroupId = null;
let groupsById = new Map();
let overlayLayer = null;
let generation = 0;

export function init(mapArg, _deviceListEl) {
  map = mapArg;
  overlayLayer = L.layerGroup().addTo(map);
  initDialog(loadGroups);
  // Same locked-boot swallow as loadGroups() below: init() renders the cards,
  // which 401s while the lock screen is up, and an uncaught rejection there is
  // a page error (cli/tests/test_ui_browser.py asserts there are none).
  groupsList.init(document.getElementById("fp-groups-list")).catch(() => {});
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
 * Show the tab hint only while there are no groups.
 *
 * The hint points at the selector above the map, which is useless with nothing
 * to select; groups_list.js renders its own empty-state paragraph inside
 * #fp-groups-list at the same moment, so the two are never both on screen. The
 * selector is scoped to #tab-groups because the Places tab has a .fp-tab-hint
 * of its own.
 */
function updateEmptyStateHint(groupCount) {
  const hint = document.querySelector("#tab-groups .fp-tab-hint");
  if (hint) hint.hidden = groupCount > 0;
  // The second line says where groups come from, which only helps while there
  // are none (onboarding.md § 8).
  const empty = document.getElementById("fp-groups-empty-hint");
  if (empty) empty.hidden = groupCount > 0;
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
    }).bindTooltip(esc(member.name)).addTo(overlayLayer);
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
 * The phrase the API computed, with the old client-side rules as a fallback.
 *
 * The dashboard, the widget and the CLI each had their own mapping and printed
 * three different things for one state (E1 honesty round 3 F4), so the label is
 * served beside the verdict now. The fallback keeps an older daemon readable
 * and encodes the two rules that matter: `partial` with nobody diverged is not
 * divergence (round 2 F1), and `all_together` with a silent member is not the
 * whole group (round 3 F3).
 */
export function verdictLabel(presence) {
  if (presence.verdict_label) return presence.verdict_label;
  const reporting = presence.reporting_count;
  const considered = presence.considered_count;
  if (presence.verdict === "all_together") {
    return considered && reporting < considered
      ? t("groups.verdictTogetherPartial", { reporting, considered })
      : t("groups.verdictTogether");
  }
  if (presence.verdict !== "partial") return t("groups.verdictUnknown");
  if (presence.diverged && presence.diverged.length > 0) return t("groups.verdictDiverged");
  return reporting === 1 ? t("groups.verdictOnlyOneReporting") : t("groups.verdictPartial");
}

function ageLabel(member) {
  return fmtAgeMinutes(member ? member.age_minutes : null);
}

/**
 * A labelled list of member names.
 *
 * The together and diverged lists were two adjacent bare <ul>s with no
 * heading and no ::before, so nothing on screen said which was which -- only
 * the stale list described itself (honesty round 2 F11). An empty list renders
 * nothing at all rather than a heading over a void.
 */
function nameList(id, heading, deviceIds, byId) {
  const wrap = document.createElement("div");
  if (!deviceIds || deviceIds.length === 0) return wrap;
  const title = document.createElement("p");
  title.className = "fp-list-heading";
  title.textContent = heading;
  wrap.appendChild(title);
  const ul = document.createElement("ul");
  ul.id = id;
  deviceIds.forEach((deviceId) => {
    const li = document.createElement("li");
    li.textContent = (byId.get(deviceId) || {}).name || deviceId;
    ul.appendChild(li);
  });
  wrap.appendChild(ul);
  return wrap;
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
    badge.textContent = t("groups.staleBadge", { name, age: ageLabel(member) });
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
}

/**
 * Select a group from outside the dropdown, keeping the two in agreement.
 *
 * groups_list.js's card click calls this rather than selectGroup() directly,
 * so the `<select>` never keeps showing the group that was selected before.
 */
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
 * alone left `#fp-group-select`'s option list (group names) and the
 * `groupsById` cache behind, both real data surviving behind the lock
 * screen (PROMPT.md §2). Bumping `generation` also discards any in-flight
 * `selectGroup()` response that would otherwise repopulate the panel right
 * after this purge runs. lock.js still imports this one function: the dialog
 * and the card grid are fanned out to from here, not wired into lock.js.
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
