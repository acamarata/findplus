/*
 * Groups tab: the card grid.
 *
 * Purpose    : One card per group — its badge, its name, up to six member
 *              avatars, the presence verdict and the edit and delete buttons.
 *              The P1 selector above the map stays read-only and map-focused;
 *              this is where a group is created, changed or removed.
 * Inputs     : GET /api/groups and GET /api/devices (one load each), then
 *              GET /api/groups/{id}/presence?window=60 once per card.
 * Outputs    : The #fp-groups-list DOM; DELETE /api/groups/{id} on confirm.
 * Constraints: Every element is built with createElement/textContent, never raw
 *              markup, and every badge through components/badge.js. The import
 *              cycle with groups.js is real and deliberate: every cross-call
 *              happens inside a function body, long after both modules have
 *              finished evaluating, so neither sees the other half-built.
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";
import { renderBadge } from "./components/badge.js";
import { showAddDialog, openEditDialog } from "./groups_dialog.js";
import { loadGroups, selectGroupById, verdictLabel } from "./groups.js";

/** Avatars shown before the grid collapses the rest into a "+N" chip. */
const MAX_AVATARS = 6;

let listEl = null;

export async function init(container) {
  listEl = container;
  const addBtn = document.getElementById("fp-add-group-btn");
  if (addBtn) {
    addBtn.textContent = t("groups.add_button");
    addBtn.addEventListener("click", showAddDialog);
  }
  // No loadCards() here: groups.js's init() calls loadGroups() immediately
  // after this, and loadGroups() ends with loadCards(). Loading in both fired
  // GET /api/groups and GET /api/devices twice on every boot and left two
  // render passes racing over the same #fp-groups-list.
}

function clearList() {
  while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
}

function span(className, text) {
  const el = document.createElement("span");
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function cardButton(className, label, ariaLabel, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = className;
  btn.textContent = label;
  btn.setAttribute("aria-label", ariaLabel);
  btn.addEventListener("click", onClick);
  return btn;
}

/**
 * The member avatars, capped at MAX_AVATARS with a "+N" chip after them.
 *
 * A member row carries device_id/name/provider only, so the icon and colour
 * come from the device cache. A member whose device row has gone (deleted
 * between the two fetches) still renders: the badge falls back rather than
 * throwing and taking the whole grid with it.
 */
function memberAvatars(group, devicesById) {
  const wrap = span("fp-card-members");
  group.members.slice(0, MAX_AVATARS).forEach((member) => {
    const device = devicesById.get(member.device_id);
    const avatar = span("fp-avatar");
    avatar.title = member.name;
    avatar.appendChild(
      renderBadge({
        icon: (device && device.icon) || "letter",
        color: (device && device.color) || "#888888",
        label: (device && device.label) || null,
        name: member.name,
        size: 16,
      }),
    );
    wrap.appendChild(avatar);
  });
  if (group.members.length > MAX_AVATARS) {
    wrap.appendChild(span("fp-avatar", `+${group.members.length - MAX_AVATARS}`));
  }
  return wrap;
}

/** Card body (not a button) selects the group and brings its tab forward. */
function onCardClick(event, group) {
  if (event.target.closest("button")) return;
  selectGroupById(group.id);
  const tab = document.querySelector('button.fp-tab[data-tab="groups"]');
  // Reuses main.js's own tab handler rather than reimplementing switchTab.
  if (tab && !tab.classList.contains("active")) tab.click();
}

function renderCard(group, devicesById) {
  const card = document.createElement("div");
  card.className = "fp-group-card";
  card.setAttribute("data-group-id", String(group.id));

  const icon = span("fp-card-icon");
  icon.appendChild(
    renderBadge({ icon: group.icon, color: group.color, label: null, name: group.name, size: 24 }),
  );
  card.append(
    icon,
    span("fp-card-name", group.name),
    memberAvatars(group, devicesById),
    span("fp-card-verdict"),
    cardButton("fp-card-edit", t("common.edit"), t("groups.card.edit", { name: group.name }),
      () => openEditDialog(group.id, group)),
    cardButton("fp-card-delete", t("common.delete"), t("groups.card.delete", { name: group.name }),
      () => onDelete(group)),
  );
  card.addEventListener("click", (event) => onCardClick(event, group));
  return card;
}

/**
 * Fill one card's verdict badge.
 *
 * Fired per card and never awaited by loadCards(), so one slow or failing
 * presence call cannot hold up the grid. A card removed by a newer loadCards()
 * while this was in flight is dropped rather than written to.
 */
async function fetchVerdict(card, groupId) {
  const presence = await api(`/api/groups/${groupId}/presence?window=60`);
  // A newer loadCards() may have replaced this card while the call was out.
  if (!card.isConnected) return;
  const badge = card.querySelector(".fp-card-verdict");
  if (!badge) return;
  badge.className = `fp-card-verdict fp-verdict fp-verdict--${presence.verdict}`;
  badge.textContent = verdictLabel(presence);
}

async function onDelete(group) {
  if (!window.confirm(t("groups.confirm.delete", { name: group.name }))) return;
  try {
    await api(`/api/groups/${group.id}`, { method: "DELETE" });
    // loadGroups() refreshes the selector and then calls loadCards() itself
    // (the T3 wiring), so calling both here would render the grid twice.
    await loadGroups();
  } catch (err) {
    // No dialog field to write into here, and a silently surviving card would
    // be worse than an alert (places.js makes the same call).
    if (err.message !== "Locked") window.alert(err.message);
  }
}

export async function loadCards() {
  if (!listEl) return;
  const [groups, devicesResp] = await Promise.all([api("/api/groups"), api("/api/devices")]);
  const devicesById = new Map(devicesResp.devices.map((d) => [d.device_id, d]));
  clearList();
  if (groups.length === 0) {
    const empty = document.createElement("p");
    empty.className = "fp-empty-state";
    empty.textContent = t("groups.empty");
    listEl.appendChild(empty);
    return;
  }
  groups.forEach((group) => {
    const card = renderCard(group, devicesById);
    listEl.appendChild(card);
    fetchVerdict(card, group.id).catch(() => {});
  });
}

/**
 * groups.js's purge() hook for the card grid.
 *
 * Group names, member avatars and verdict text are all real data, and a closed
 * lock screen over a populated grid still leaves them in the DOM for anyone
 * with DevTools (PROMPT.md §2 invariant 11).
 */
export function purgeCards() {
  if (listEl) clearList();
}
