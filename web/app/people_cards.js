/*
 * People tab: one card per person or pet.
 *
 * Purpose    : The "People" section of the People tab. Each card shows the
 *              avatar (a button that opens the editor on icon and colour), the
 *              name, the engine's "where" sentence, the tracker badges, any
 *              "looks left behind" chips for that person, and the buttons
 *              Open (the Person page), Edit (the person editor) and Delete
 *              (danger, still confirms). Pets use the same card; the engine
 *              already words their sentence.
 * Inputs     : renderPeopleCards(persons, devicesById): the person/pet rows of
 *              GET /api/groups and the device cache from GET /api/devices;
 *              GET /api/people/{id}/now, /api/people and
 *              /api/people/{id}/left-behind fill the sentence and chips.
 * Outputs    : Cards inside #fp-people-list, "Add person" in the section
 *              header (mountPeopleCards). Cards keep the legacy hooks
 *              `.fp-group-card[data-group-id]`, `.fp-card-edit`, `.fp-card-delete`.
 * Constraints: createElement/textContent only. A failed side lookup leaves the
 *              slot empty. A card replaced by a newer render is never written to.
 *              purgePeopleCards() empties the list on lock.
 */
"use strict";

import { t } from "./i18n.js";
import { button } from "./components/button.js";
import { markForLinks } from "./person_links.js";
import { explainSlot } from "./groups_card_meta.js";
import { fillWhereNow, personCardIcon, personMeta } from "./groups_person_card.js";
import { fetchLeftBehind, fetchPeople } from "./person_api.js";
import { personHref } from "./person_hash.js";
import { thing } from "./left_behind_chips.js";
import { openPersonEditor, openPersonCreate } from "./person_editor.js";
import { memberAvatars, onDelete } from "./groups_list.js";
import { loadGroups } from "./groups.js";

let listEl = null;

function span(className, text) {
  const el = document.createElement("span");
  el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

/** Wire the section: the list host and the header's Add person button (once). */
export function mountPeopleCards() {
  listEl = document.getElementById("fp-people-list");
  const slot = document.getElementById("fp-add-person-slot");
  if (!slot || slot.firstChild) return;
  slot.appendChild(button({
    label: t("peoplePane.addPerson"), icon: "plus", variant: "primary", size: "sm", id: "fp-add-person-btn",
    onClick: () => openPersonCreate(loadGroups).catch((err) => console.error("add person failed", err)),
  }));
}

function cardActions(group) {
  const box = document.createElement("div");
  box.className = "fp-card-actions";
  const named = (key) => ({ "aria-label": t(key, { name: group.name }) });
  box.append(
    button({ label: t("peoplePane.open"), icon: "user", size: "sm", attrs: named("peoplePane.openFor"),
      onClick: () => { window.location.hash = personHref(group.id); } }),
    button({ label: t("common.edit"), icon: "pencil", size: "sm", attrs: named("groups.card.edit"),
      onClick: () => openPersonEditor(group.id, loadGroups) }),
    button({ label: t("common.delete"), icon: "trash-2", size: "sm", variant: "danger", attrs: named("groups.card.delete"),
      onClick: () => onDelete(group) }),
  );
  box.querySelectorAll("button").forEach((b, i) => b.classList.add(["fp-card-open", "fp-card-edit", "fp-card-delete"][i]));
  return box;
}

function renderCard(group, devicesById) {
  const card = document.createElement("div");
  card.className = "fp-group-card fp-person-card";
  card.setAttribute("data-group-id", String(group.id));
  const chips = span("fp-card-chips");
  chips.hidden = true;
  card.append(
    personCardIcon(group, loadGroups),
    markForLinks(span("fp-card-name", group.name)),
    memberAvatars(group, devicesById),
    personMeta(group),
    explainSlot(),
    chips,
    cardActions(group),
  );
  return card;
}

/** "Bag looks left at School" chips for one person, from confirmed episodes only. */
async function fillChips(card, group, person) {
  let episodes;
  try {
    episodes = await fetchLeftBehind(group.id);
  } catch (_) {
    return;
  }
  const slot = card.isConnected && card.querySelector(".fp-card-chips");
  const left = episodes.filter((e) => e.state === "left_behind");
  if (!slot || left.length === 0) return;
  const who = person || { name: group.name, trackers: [] };
  left.forEach((e) => {
    const key = e.place_name ? "peoplePane.leftChip" : "peoplePane.leftChipSpot";
    slot.appendChild(span("fp-card-chip", t(key, { tracker: thing(who, e), place: e.place_name })));
  });
  slot.hidden = false;
}

/** Redraw the section from the group rows that are people or pets. */
export function renderPeopleCards(persons, devicesById) {
  if (!listEl) return;
  listEl.replaceChildren();
  if (persons.length === 0) {
    const empty = document.createElement("p");
    empty.className = "fp-empty-state";
    empty.textContent = t("peoplePane.empty");
    listEl.appendChild(empty);
    return;
  }
  const cards = persons.map((group) => ({ group, card: renderCard(group, devicesById) }));
  listEl.append(...cards.map((c) => c.card));
  // Not awaited: the sentence and the chips fill in as they arrive.
  fetchPeople().catch(() => []).then((people) => cards.forEach(({ group, card }) => {
    fillWhereNow(card, group);
    fillChips(card, group, people.find((p) => p.id === group.id)).catch(() => {});
  }));
}

/** Lock purge: names, trackers and places must not survive in the page. */
export function purgePeopleCards() {
  if (listEl) listEl.replaceChildren();
}
