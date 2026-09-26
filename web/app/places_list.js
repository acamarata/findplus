/*
 * Places tab: the side-panel list (UAT U5).
 *
 * Purpose    : One row per saved place — its colour, its radius and which
 *              tracked devices are inside it right now — with Edit, Delete
 *              and click-to-centre. Before this the side panel showed only
 *              the "Add place" button and a hint; a place off the visible
 *              map edge could not be found, edited or deleted at all.
 * Inputs     : GET /api/places, GET /api/devices and GET
 *              /api/places/presence — one fetch of each per refresh(), the
 *              same shape groups_list.js uses for its own card grid.
 * Outputs    : The #fp-places-list DOM. Edit/Delete/centre delegate to
 *              places.js, which owns the circle registry and the dialog.
 * Constraints: Every element is built with createElement/textContent, never
 *              raw markup. The places.js import cycle is real and
 *              deliberate (same shape as groups.js/groups_list.js): every
 *              cross-call happens inside a function body, long after both
 *              modules have finished evaluating, so neither sees the other
 *              half-built.
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";
import { displayName } from "./state.js";
import { editPlace, deletePlace, centerOnPlace } from "./places.js";

let listEl = null;

export function init(container) {
  listEl = container;
}

function clearList() {
  if (!listEl) return;
  while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
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

/** Every tracked device's display name currently inside this place, joined
 * for one line — or nothing at all when the row stays plain rather than
 * announcing an empty "Currently here:" on every place with nobody in it. */
function whoIsHereText(place, presenceByPlace, devicesById) {
  const here = (presenceByPlace.get(String(place.id)) || [])
    .map((deviceId) => displayName(devicesById.get(deviceId)) || deviceId);
  return here.length ? t("places.list.whoIsHere", { names: here.join(", ") }) : "";
}

/** Card body (not a button) centres the map on the place — U5's click-to-centre. */
function onCardClick(event, place) {
  if (event.target.closest("button")) return;
  centerOnPlace(place.id);
}

function renderCard(place, presenceByPlace, devicesById) {
  const card = document.createElement("div");
  card.className = "fp-place-card";
  card.setAttribute("data-place-id", String(place.id));

  const dot = document.createElement("span");
  dot.className = "fp-color-swatch";
  dot.style.background = place.color;
  dot.setAttribute("aria-hidden", "true");

  const name = document.createElement("span");
  name.className = "fp-card-name";
  name.textContent = place.name;

  const meta = document.createElement("span");
  meta.className = "fp-place-card-meta";
  meta.textContent = t("places.list.radiusMeta", { radius: place.radius_meters });

  const who = document.createElement("span");
  who.className = "fp-place-card-who";
  who.textContent = whoIsHereText(place, presenceByPlace, devicesById);

  card.append(
    dot,
    name,
    meta,
    who,
    // V1: these had no button class at all (fully browser-default); devices.js's
    // own row-edit button is the precedent for this exact "btn btn-tiny" pairing.
    cardButton("fp-card-edit btn btn-tiny", t("common.edit"), t("places.card.edit", { name: place.name }),
      () => editPlace(place.id)),
    cardButton("fp-card-delete btn btn-tiny", t("common.delete"), t("places.card.delete", { name: place.name }),
      () => deletePlace(place.id)),
  );
  card.addEventListener("click", (event) => onCardClick(event, place));
  return card;
}

/** place_id -> [device_id, ...] currently inside, from the same presence
 * feed places.js's own chips read — one shared shape, two renderings. */
function groupPresenceByPlace(entries) {
  const out = new Map();
  entries
    .filter((entry) => entry.state === "inside")
    .forEach((entry) => {
      const key = String(entry.place_id);
      if (!out.has(key)) out.set(key, []);
      out.get(key).push(entry.device_id);
    });
  return out;
}

/** N26: the tab hint ("Use Add place…") only helps before any place exists;
 * once one does, it just sits above the list forever saying something the
 * user has already done (the mirror of groups.js's own updateEmptyStateHint(),
 * whose hint shows only once a group DOES exist — the two hints point
 * opposite directions on purpose, since one explains how to get started and
 * the other how to use what already exists). */
function updateTabHint(placeCount) {
  const hint = document.getElementById("fp-places-tab-hint");
  if (hint) hint.hidden = placeCount > 0;
}

export async function refresh() {
  if (!listEl) return;
  const [places, devicesResp, presence] = await Promise.all([
    api("/api/places"),
    api("/api/devices"),
    api("/api/places/presence"),
  ]);
  const devicesById = new Map(devicesResp.devices.map((d) => [d.device_id, d]));
  const presenceByPlace = groupPresenceByPlace(presence);
  updateTabHint(places.length);
  clearList();
  // U14: places.html's own .fp-tab-hint ("Use Add place to create a
  // geofence") sits right above #fp-places-list and already is the empty
  // state's one message; a second paragraph here duplicated it.
  if (places.length === 0) return;
  places.forEach((place) => listEl.appendChild(renderCard(place, presenceByPlace, devicesById)));
}

/**
 * places.js's purge() hook for the list.
 *
 * A place's name and who-is-here text are real location data left readable
 * behind the lock screen otherwise (PROMPT.md §2 invariant 11) — same reason
 * groups_list.js's own purgeCards() exists.
 */
export function purgeList() {
  clearList();
}
