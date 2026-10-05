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
import { uniqueLabel } from "./device_label.js";
import { t, plural } from "./i18n.js";
import { renderBadge } from "./components/badge.js";
import { button, styleAsButton } from "./components/button.js";
import { markForLinks } from "./person_links.js";
import { showAddDialog, openEditDialog } from "./groups_dialog.js";
import { loadGroups, selectGroupById, clearGroup, isGroupSelected } from "./groups.js";
import { verdictLabel, verdictTitle } from "./groups_presence_render.js";
import { confirmDialog, alertDialog } from "./components/confirm-dialog.js";
import { metaLine, explainSlot, fillExplanation } from "./groups_card_meta.js";
import { isPerson } from "./groups_person_card.js";
import { mountPeopleCards, renderPeopleCards, purgePeopleCards } from "./people_cards.js";

/** Avatars shown before the grid collapses the rest into a "+N" chip. */
const MAX_AVATARS = 6;

let listEl = null;

export async function init(container) {
  listEl = container;
  mountPeopleCards();
  const addBtn = document.getElementById("fp-add-group-btn");
  if (addBtn) {
    addBtn.textContent = t("groups.add_button");
    styleAsButton(addBtn, { icon: "plus", variant: "secondary" });
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

/** Replace the card grid with one error pane (groups.js's failed-load state). */
export function showListError(pane) {
  if (!listEl) return;
  clearList();
  listEl.appendChild(pane);
}

function span(className, text) {
  const el = document.createElement("span");
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

/** A card button on the 1.3 button system; `hook` keeps the legacy class tests and CSS use. */
function cardButton(hook, label, ariaLabel, onClick, { icon, variant = "secondary" } = {}) {
  const btn = button({ label, icon, variant, size: "sm", onClick, attrs: { "aria-label": ariaLabel } });
  btn.classList.add(hook);
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
export function memberAvatars(group, devicesById) {
  const wrap = span("fp-card-members");
  group.members.slice(0, MAX_AVATARS).forEach((member) => {
    const device = devicesById.get(member.device_id);
    // UAT U6: the group member list is one of the surfaces that must show
    // the label, not the raw provider name -- member.name is the fallback
    // for a device row that has since been deleted (see the docstring above).
    const shown = uniqueLabel(device) || member.name;
    // N27: a 16px, mouse-only title tooltip was the only place a member's
    // name showed at all -- fp-avatar--lg (places-events.css) draws it
    // bigger, and tabindex/aria-label/role make the name reachable by
    // keyboard focus too, not only a hover a touch or keyboard user cannot make.
    const avatar = span("fp-avatar fp-avatar--lg");
    avatar.title = shown;
    avatar.tabIndex = 0;
    avatar.setAttribute("role", "img");
    avatar.setAttribute("aria-label", shown);
    avatar.appendChild(
      renderBadge({
        icon: (device && device.icon) || "letter",
        color: (device && device.color) || "#888888",
        label: (device && device.label) || null,
        name: shown,
        size: 22,
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
  if (event.target.closest("button, a")) return;
  selectGroupById(group.id);
  const tab = document.querySelector('button.fp-tab[data-tab="people"]');
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
  // UAT3 N24: Edit and Delete are one flex item, so they wrap as a pair or not at all.
  const actions = document.createElement("div");
  actions.className = "fp-card-actions";
  actions.append(
    cardButton("fp-card-edit", t("common.edit"), t("groups.card.edit", { name: group.name }),
      () => openEditDialog(group.id, group), { icon: "pencil" }),
    cardButton("fp-card-delete", t("common.delete"), t("groups.card.delete", { name: group.name }),
      () => onDelete(group), { icon: "trash-2", variant: "danger" }),
  );
  card.append(
    icon,
    markForLinks(span("fp-card-name", group.name)),
    memberAvatars(group, devicesById),
    metaLine(group, devicesById),
    span("fp-card-verdict"),
    actions,
    explainSlot(),
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
  badge.title = verdictTitle(presence);
  fillExplanation(card, presence);
}

/** A failed presence call left the pill blank, which read as "still loading". */
function showVerdictUnavailable(card) {
  const badge = card.querySelector(".fp-card-verdict");
  if (!badge || !card.isConnected) return;
  badge.className = "fp-card-verdict fp-verdict fp-verdict--unknown";
  badge.textContent = t("groups.verdictUnavailable");
  badge.title = t("groups.verdictUnavailableHint");
}

/** How many alert rules point at this group -- see places.js's
 *  countPlaceRules() docstring; AlertRule.group_id is the same
 *  ondelete="CASCADE" FK, so this is the truth, not a guess. */
async function countGroupRules(id) {
  try {
    const rules = await api("/api/alerts/rules");
    return rules.filter((r) => Number(r.group_id) === Number(id)).length;
  } catch (_) {
    return 0;
  }
}

export async function onDelete(group) {
  const ruleCount = await countGroupRules(group.id);
  const confirmed = await confirmDialog({
    title: t("groups.confirm.delete", { name: group.name }),
    body: ruleCount > 0 ? plural("groups.confirm.deleteRules", ruleCount, { count: ruleCount }) : "",
    confirmLabel: t("common.delete"),
    danger: true,
  });
  if (!confirmed) return;
  try {
    await api(`/api/groups/${group.id}`, { method: "DELETE" });
    // UAT4 N31: deleting the group the presence panel is currently showing
    // must clear it, not leave the deleted group's verdict/note on screen --
    // loadGroups() below only refreshes the selector and card grid.
    if (isGroupSelected(group.id)) clearGroup();
    // loadGroups() refreshes the selector and then calls loadCards() itself
    // (the T3 wiring), so calling both here would render the grid twice.
    await loadGroups();
  } catch (err) {
    // No dialog field to write into here, and a silently surviving card would
    // be worse than an alert (places.js makes the same call).
    if (err.message !== "Locked") await alertDialog({ title: t("common.errorTitle"), body: err.message });
  }
}

export async function loadCards() {
  if (!listEl) return;
  const [groups, devicesResp] = await Promise.all([api("/api/groups"), api("/api/devices")]);
  const devicesById = new Map(devicesResp.devices.map((d) => [d.device_id, d]));
  // People and pets draw in the People section (people_cards.js); this list is the other groups.
  renderPeopleCards(groups.filter(isPerson), devicesById);
  const others = groups.filter((g) => !isPerson(g));
  clearList();
  if (others.length === 0) {
    const empty = document.createElement("p");
    empty.className = "fp-empty-state";
    empty.textContent = t(groups.length === 0 ? "groups.empty" : "peoplePane.noGroups");
    listEl.appendChild(empty);
    return;
  }
  others.forEach((group) => {
    const card = renderCard(group, devicesById);
    listEl.appendChild(card);
    fetchVerdict(card, group.id).catch(() => showVerdictUnavailable(card));
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
  purgePeopleCards();
}
