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
import { t, plural } from "./i18n.js";
import { uniqueLabel } from "./device_label.js";
import { editPlace, deletePlace, centerOnPlace, refreshAll, offerRuleFor } from "./places.js";
import { paneError } from "./pane_error.js";
import { showAlert } from "./state.js";
import { activeQuery, applyTools, buildTools, reset as resetTools, toolsVisible } from "./places_list_tools.js";

/** The last fetch, so search/sort re-render without another round trip. */
let last = null;

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
    .map((deviceId) => uniqueLabel(devicesById.get(deviceId)) || deviceId);
  return here.length ? t("places.list.whoIsHere", { names: here.join(", ") }) : "";
}

/** Card body (not a button) centres the map on the place — U5's click-to-centre. */
function onCardClick(event, place) {
  if (event.target.closest("button")) return;
  centerOnPlace(place.id);
}

/** "200 m radius · 41.1000, -80.1000 · 2 alert rules": everything a place is, in one line.
 * A place with no rule says so, with a button: it messages nobody on its own. */
function metaText(place, ruleCount) {
  const parts = [
    t("places.list.radiusMeta", { radius: place.radius_meters }),
    t("places.list.coords", { lat: place.latitude.toFixed(4), lon: place.longitude.toFixed(4) }),
  ];
  if (ruleCount > 0) parts.push(plural("places.list.rules", ruleCount, { count: ruleCount }));
  return parts.join(" · ");
}

function notifyRow(place) {
  const row = document.createElement("span");
  row.className = "fp-place-notify";
  const text = document.createElement("span");
  text.textContent = t("places.list.notNotifying");
  row.append(text, cardButton("btn btn-tiny fp-place-notify-btn", t("places.list.setUpAlert"),
    t("places.list.setUpAlertFor", { name: place.name }), () => offerRuleFor(place.id)));
  return row;
}

/** A kind Find+ guessed from the name (an upgraded place, or one added
 * without picking): say so, with a one-tap confirm. Edit changes it. */
function kindRow(place) {
  const row = document.createElement("span");
  row.className = "fp-place-kind-guess";
  const kind = t(`places.kind.${place.kind}`);
  const text = document.createElement("span");
  text.textContent = t("places.list.kindGuess", { kind });
  row.append(text, cardButton("btn btn-tiny fp-place-kind-confirm", t("places.list.kindConfirm"),
    t("places.list.kindConfirmFor", { name: place.name, kind }), () => confirmKind(place)));
  return row;
}

async function confirmKind(place) {
  try {
    await api(`/api/places/${place.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: place.kind }),
    });
  } catch (err) {
    showAlert(t("places.list.kindConfirmFailed", { message: err.message || String(err) }), "err");
    return;
  }
  await refreshAll();
}

function renderCard(place, presenceByPlace, devicesById, ruleCount) {
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
  meta.textContent = metaText(place, ruleCount);

  const who = document.createElement("span");
  who.className = "fp-place-card-who";
  who.textContent = whoIsHereText(place, presenceByPlace, devicesById);

  card.append(
    dot,
    name,
    meta,
    who,
    ...(place.kind_guessed ? [kindRow(place)] : []),
    ...(ruleCount === 0 ? [notifyRow(place)] : []),
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

/** The list while the first fetch is out. The "Use Add place" hint stays hidden:
 * it says no place exists, which nobody knows yet (UAT #13). */
export function showLoading() {
  if (!listEl) return;
  updateTabHint(1);
  const note = document.createElement("p");
  note.className = "fp-empty-state";
  note.setAttribute("role", "status");
  note.textContent = t("common.loading");
  listEl.replaceChildren(note);
}

/** A failed load: say so, with Retry, rather than the "no places yet" hint. */
export function showError(err) {
  if (!listEl) return;
  updateTabHint(1);
  listEl.replaceChildren(
    paneError({ title: t("places.loadFailedTitle"), message: err.message, onRetry: () => { showLoading(); refreshAll(); } })
  );
}

/** place_id -> how many alert rules use it. A failed rules fetch reads as none:
 * the list must never be blocked by a count. */
async function ruleCounts() {
  try {
    const rules = await api("/api/alerts/rules");
    const counts = new Map();
    rules.forEach((r) => counts.set(String(r.place_id), (counts.get(String(r.place_id)) || 0) + 1));
    return counts;
  } catch (_) {
    return new Map();
  }
}

/** Draw `last` through the search and sort. */
function render() {
  if (!listEl || !last) return;
  const { places, presenceByPlace, devicesById, counts } = last;
  updateTabHint(places.length);
  // U14: places.html's own .fp-tab-hint is the empty state's one message.
  if (places.length === 0) return clearList();
  // The toolbar node stays put between renders: moving it would drop focus
  // from the search box in the middle of a word.
  const tools = buildTools(render);
  [...listEl.children].forEach((child) => child !== tools && child.remove());
  if (!tools.isConnected) listEl.prepend(tools);
  toolsVisible(places.length);
  const shown = applyTools(places);
  shown.forEach((place) =>
    listEl.appendChild(renderCard(place, presenceByPlace, devicesById, counts.get(String(place.id)) || 0)));
  if (shown.length === 0) {
    const none = document.createElement("p");
    none.className = "fp-empty-state";
    none.textContent = t("places.tools.noMatch", { query: activeQuery() });
    listEl.appendChild(none);
  }
}

export async function refresh() {
  if (!listEl) return;
  const [places, devicesResp, presence, counts] = await Promise.all([
    api("/api/places"),
    api("/api/devices"),
    api("/api/places/presence"),
    ruleCounts(),
  ]);
  const devicesById = new Map(devicesResp.devices.map((d) => [d.device_id, d]));
  last = { places, presenceByPlace: groupPresenceByPlace(presence), devicesById, counts };
  render();
}

/**
 * places.js's purge() hook for the list.
 *
 * A place's name and who-is-here text are real location data left readable
 * behind the lock screen otherwise (PROMPT.md §2 invariant 11) — same reason
 * groups_list.js's own purgeCards() exists.
 */
export function purgeList() {
  last = null;
  resetTools();
  clearList();
}
