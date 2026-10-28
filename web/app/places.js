/*
 * Places tab: geofence circles + presence chips. The add/edit dialog lives
 * in places_dialog.js, the side-panel list in places_list.js (both split
 * out at the PRI rule-7 300-line file cap).
 *
 * Purpose    : Surface E5's places/geofence engine — draw saved places as
 *              L.Circle layers, own the place/circle registries, and inject
 *              a presence chip into each device row showing which place a
 *              tracker is inside.
 * Inputs     : GET /api/places, GET /api/places/presence; DELETE
 *              /api/places/{id} on delete (add/edit POST/PUT is
 *              places_dialog.js's).
 * Outputs    : A Leaflet layer group of place circles; .fp-presence-chip
 *              spans appended to device rows.
 * Constraints: Every element below is built with createElement/textContent,
 *              never raw markup assignment, so API-sourced strings can never
 *              run as script. The places_list.js import cycle is real and
 *              deliberate (same shape as groups.js/groups_list.js): every
 *              cross-call happens inside a function body, long after both
 *              modules have finished evaluating.
 */
"use strict";

import { api } from "./api.js";
import { state, showAlert, fmtAgeMinutes, esc } from "./state.js";
import { t, plural } from "./i18n.js";
import { initDialog, openEditDialog, purgeDialog, showAddDialog } from "./places_dialog.js";
import { gateAddOnLoadError } from "./places_error_gate.js";
import * as placesList from "./places_list.js";
import * as placesEvents from "./places_events.js";
import { mountNoticed } from "./places_noticed.js";
import { initBackfill, purgeBackfill, refreshBackfill, refreshRules } from "./places_backfill.js";
import { confirmDialog } from "./components/confirm-dialog.js";

let map = null;
let placeLayer = null;
let placesById = new Map();
let circlesById = new Map();
let noticed = null;

export function init(mapArg, _deviceListEl) {
  map = mapArg;
  placeLayer = L.layerGroup().addTo(map);
  initDialog(map, { onSaved: onPlaceSaved });
  placesList.init(document.getElementById("fp-places-list"));
  placesEvents.init(document.getElementById("fp-places-events"));
  initBackfill(document.getElementById("fp-places-backfill"), refreshAll);
  const noticedHost = document.getElementById("fp-places-noticed");
  if (noticedHost) noticed = mountNoticed(noticedHost, { onSaved: (place) => onPlaceSaved(place, "add") });
  const addBtn = document.getElementById("fp-add-place-btn");
  // UAT U4/U10: used to arm a mouse-only crosshair mode; opening the dialog
  // straight at the map's current centre needs no map click at all, so a
  // native <button> (already a Tab stop, already fires on Enter/Space) is
  // now the whole affordance.
  // N26: the Nth place added gets the Nth palette entry as its default
  // colour instead of every place starting the same blue -- placesById is
  // already current here, loadPlaces() having run at boot before a user can
  // click this at all.
  if (addBtn) addBtn.addEventListener("click", () => openPlaceSheet({ mode: "add" }));
  gateAddOnLoadError(document.getElementById("fp-places-list"), addBtn);
  // UAT2 N12: main.js awaits refreshLockState() before calling init(), so
  // state.locked is already known here -- skip the fetch rather than fire it
  // and swallow a 401. lock.js's refreshTabsAfterUnlock() calls refreshAll()
  // again once unlocked.
  if (!state.locked) {
    placesList.showLoading();
    refreshAll();
  }
}

/** A place says nothing on its own. After a NEW one is saved, go straight to
 * "who should be told, and where", with the place already chosen. */
async function onPlaceSaved(place, mode) {
  await loadPlaces();
  import("./people_replay.js").then((m) => m.watchReplay()).catch(() => {});
  if (mode === "add" && place) announceDefaultRule(place);
}

/** The place dialog's "Tell me when anyone arrives or leaves" box made the rule already:
 * say so in one line, with a way to change it. No second dialog opens by itself. */
function announceDefaultRule(place) {
  const rule = place.notify_rule;
  if (!rule) return;
  refreshRules();
  const channels = rule.channels.map((c) => t(`alerts.channels.${c}`)).join(", ");
  const text = rule.enabled === false
    ? `${t("places.notify.savedOff", { place: place.name })} ${rule.hint || ""}`.trim()
    : rule.hint
      ? `${t("places.notify.onPlain", { place: place.name })} ${rule.hint}`
      : t("places.notify.on", { place: place.name, channels });
  showAlert(text, "info", { action: { label: t("places.notify.customise"), run: () => customiseRule(place, rule.id) } });
}

/** "Customise": the rule dialog on the rule that was just made. */
async function customiseRule(place, ruleId) {
  const { openRuleDialog } = await import("./alerts_rule_dialog.js");
  const rule = (await api("/api/alerts/rules")).find((r) => r.id === ruleId);
  if (rule) await openRuleDialog(rule, { intro: t("places.notify.customiseIntro", { place: place.name }) });
}

/** The rule dialog for `place`; also the list card's "Set up an alert" button. */
export async function offerRule(place) {
  const { openRuleDialog } = await import("./alerts_rule_dialog.js");
  await openRuleDialog(null, {
    placeId: place.id,
    intro: t("alerts.ruleIntroAfterPlace", { place: place.name }),
  });
}

export async function offerRuleFor(id) {
  const place = placesById.get(String(id));
  if (place) await offerRule(place);
}

export async function refreshAll() {
  try {
    await loadPlaces();
    await loadPresence();
  } catch (err) {
    // Locked: the lock screen takes over. Anything else gets the list's own
    // error state with Retry, and no circles left from an earlier good load.
    if (err.message === "Locked") return;
    if (placeLayer) placeLayer.clearLayers();
    placesById = new Map();
    circlesById.clear();
    placesList.showError(err);
  }
}

/** lock.js purgeRenderedData() hook: a circle or chip left behind is real location data. */
export function purge() {
  if (placeLayer) placeLayer.clearLayers();
  purgeDialog();
  placesList.purgeList();
  placesEvents.purge();
  purgeBackfill();
  if (noticed) noticed.purge();
  placesById = new Map();
  circlesById.clear();
  document.querySelectorAll(".fp-presence-chip").forEach((chip) => chip.remove());
}

export async function loadPlaces() {
  const places = await api("/api/places");
  placeLayer.clearLayers();
  circlesById.clear();
  placesById = new Map(places.map((p) => [String(p.id), p]));
  places.forEach((place) => {
    const circle = L.circle([place.latitude, place.longitude], {
      radius: place.radius_meters, color: place.color, fillOpacity: 0.15, keyboard: false, className: "fp-place-circle",
    })
      // N26: an unlabelled circle only says which one is which through its
      // colour, which two places can share (or look alike in dark mode) --
      // a permanent label reads directly off the map with no click needed.
      // esc(): a place name reaches Leaflet's tooltip content, which treats
      // a bare string as HTML (esc() is the same guard groups_presence_render.js
      // uses for a member name on the same kind of circle tooltip).
      .bindTooltip(esc(place.name), { permanent: true, direction: "center", className: "fp-place-tooltip" })
      .bindPopup(buildPlacePopup(place));
    circle.addTo(placeLayer);
    circlesById.set(String(place.id), circle);
  });
  // U5: the side panel is a second rendering of the same fetch, the same
  // shape groups.js/groups_list.js already use — its own refresh() does an
  // independent GET /api/devices + /api/places/presence for the "who is
  // here now" column, so it stays correct even when only presence changed.
  await placesList.refresh();
  refreshBackfill();
  // P19/WP9: an add/edit/delete (this function's every caller) is also a
  // good moment to catch up the arrivals/departures panel; its own timer
  // (places_events.js) covers "refresh after a poll" for the gap between
  // these without this module needing to know when a poll happened.
  await placesEvents.refresh();
  // Slow on a long history, and the tab is useful without it: never awaited.
  if (noticed) noticed.refresh();
}

/** Pans to a place and reopens its map popup — the list row's click-to-centre
 * (U5). Exported rather than duplicated: places_list.js has no circle
 * registry of its own. */
export function centerOnPlace(id) {
  const place = placesById.get(String(id));
  const circle = circlesById.get(String(id));
  if (!place || !map) return;
  map.setView([place.latitude, place.longitude], Math.max(map.getZoom(), 15));
  if (circle) circle.openPopup();
}

function button(text, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = text;
  btn.addEventListener("click", onClick);
  return btn;
}

function buildPlacePopup(place) {
  const box = document.createElement("div");
  box.className = "fp-place-popup";
  const name = document.createElement("div");
  name.textContent = place.name;
  box.appendChild(name);
  box.appendChild(button(t("common.edit"), () => editPlace(place.id)));
  box.appendChild(button(t("common.delete"), () => deletePlace(place.id)));
  return box;
}

/**
 * The one stable way to open the place sheet from anywhere (the App bar's
 * "Add > Place", the setup wizard): `{ mode: "add" }` opens it at the map's
 * centre with the first unused palette colour; `{ mode: "edit", placeId }`
 * opens that place. Resolves once the sheet is open.
 */
export async function openPlaceSheet({ mode = "add", placeId } = {}) {
  if (mode === "edit") return editPlace(placeId);
  if (!map) return undefined;
  return showAddDialog(map.getCenter(), [...placesById.values()].map((p) => p.color));
}

/** Exported so places_list.js's own Edit button reuses this instead of a
 * second lookup — it shares placesById, which is private to this module. */
export async function editPlace(id) {
  const place = placesById.get(String(id));
  if (!place) return;
  openEditDialog(id, place, await countPlaceRules(id));
}

/** How many alert rules point at this place, so the delete confirm can say
 *  the truth: `AlertRule.place_id` is `ondelete="CASCADE"` (models_alerts.py),
 *  so deleting the place really does delete these rows too, not just orphan
 *  them. Falls back to 0 (sentence omitted) if the rules fetch itself fails --
 *  losing the count is better than blocking the delete over it. */
async function countPlaceRules(id) {
  try {
    const rules = await api("/api/alerts/rules");
    return rules.filter((r) => Number(r.place_id) === Number(id)).length;
  } catch (_) {
    return 0;
  }
}

export async function deletePlace(id) {
  const place = placesById.get(String(id));
  const ruleCount = await countPlaceRules(id);
  const confirmed = await confirmDialog({
    title: t("places.confirmDelete", { name: place ? place.name : id }),
    body: ruleCount > 0 ? plural("places.confirmDeleteRules", ruleCount, { count: ruleCount }) : "",
    confirmLabel: t("common.delete"),
    danger: true,
  });
  if (!confirmed) return;
  try {
    await api(`/api/places/${id}`, { method: "DELETE" });
  } catch (err) {
    // A bare return left the circle on the map with nothing said (round 3 F10).
    showAlert(t("places.deleteFailed", { status: err.status || err.message }), "err");
    return;
  }
  const circle = circlesById.get(String(id));
  if (circle) {
    placeLayer.removeLayer(circle);
    circlesById.delete(String(id));
  }
  placesById.delete(String(id));
  await loadPresence();
  await placesList.refresh();
  await placesEvents.refresh();
}

/* ------------------------------------------------------------- presence */

export async function loadPresence() {
  let entries;
  try {
    entries = await api("/api/places/presence");
  } catch (_) {
    return;
  }
  entries
    .filter((entry) => entry.state === "inside")
    .forEach((entry) => {
      const row = document.querySelector(`[data-device-id="${entry.device_id}"]`);
      if (!row) return;
      let chip = row.querySelector(".fp-presence-chip");
      if (!chip) {
        chip = document.createElement("span");
        chip.className = "fp-presence-chip";
        row.appendChild(chip);
      }
      chip.textContent = t("places.sinceLabel", {
        place: entry.place_name,
        time: relativeTime(entry.since_observed_at),
      });
    });
}

function relativeTime(iso) {
  if (!iso) return t("common.unknown");
  return fmtAgeMinutes(Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
}
