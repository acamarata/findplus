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
import { t } from "./i18n.js";
import { initDialog, openEditDialog, purgeDialog, showAddDialog } from "./places_dialog.js";
import * as placesList from "./places_list.js";
import * as placesEvents from "./places_events.js";
import { confirmDialog } from "./components/confirm-dialog.js";

let map = null;
let placeLayer = null;
let placesById = new Map();
let circlesById = new Map();

export function init(mapArg, _deviceListEl) {
  map = mapArg;
  placeLayer = L.layerGroup().addTo(map);
  initDialog(map, { onSaved: loadPlaces });
  placesList.init(document.getElementById("fp-places-list"));
  placesEvents.init(document.getElementById("fp-places-events"));
  const addBtn = document.getElementById("fp-add-place-btn");
  // UAT U4/U10: used to arm a mouse-only crosshair mode; opening the dialog
  // straight at the map's current centre needs no map click at all, so a
  // native <button> (already a Tab stop, already fires on Enter/Space) is
  // now the whole affordance.
  // N26: the Nth place added gets the Nth palette entry as its default
  // colour instead of every place starting the same blue -- placesById is
  // already current here, loadPlaces() having run at boot before a user can
  // click this at all.
  if (addBtn) addBtn.addEventListener("click", () => showAddDialog(map.getCenter(), placesById.size));
  // UAT2 N12: main.js awaits refreshLockState() before calling init(), so
  // state.locked is already known here -- skip the fetch rather than fire it
  // and swallow a 401. lock.js's refreshTabsAfterUnlock() calls refreshAll()
  // again once unlocked.
  if (!state.locked) refreshAll();
}

export async function refreshAll() {
  try {
    await loadPlaces();
    await loadPresence();
  } catch (_) {
    // Locked or unreachable at boot; the lock screen / next refresh handles it.
  }
}

/** lock.js purgeRenderedData() hook: a circle or chip left behind is real location data. */
export function purge() {
  if (placeLayer) placeLayer.clearLayers();
  purgeDialog();
  placesList.purgeList();
  placesEvents.purge();
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
      radius: place.radius_meters, color: place.color, fillOpacity: 0.15, keyboard: false,
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
  // P19/WP9: an add/edit/delete (this function's every caller) is also a
  // good moment to catch up the arrivals/departures panel; its own timer
  // (places_events.js) covers "refresh after a poll" for the gap between
  // these without this module needing to know when a poll happened.
  await placesEvents.refresh();
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

/** Exported so places_list.js's own Edit button reuses this instead of a
 * second lookup — it shares placesById, which is private to this module. */
export async function editPlace(id) {
  const place = placesById.get(String(id));
  if (!place) return;
  openEditDialog(id, place);
}

export async function deletePlace(id) {
  const place = placesById.get(String(id));
  const confirmed = await confirmDialog({
    title: t("common.delete"),
    body: t("places.confirmDelete", { name: place ? place.name : id }),
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
