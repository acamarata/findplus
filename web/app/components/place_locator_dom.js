/*
 * Place locator: element construction.
 *
 * Purpose    : Build the "use a tracker" row, the "Pick on map" button and
 *              the address-search group place_locator.js's
 *              createPlaceLocator() mounts into a place dialog. Split out of
 *              place_locator.js at the PRI rule-7 50-line function cap (E13
 *              loop-1 follow-up), the same way groups_dialog_dom.js
 *              separates construction from groups_dialog.js's behavior.
 * Inputs     : The `host` element buildPlaceLocatorDom() mounts into; a
 *              tracked device for trackerOption(); one Nominatim result row
 *              for searchResultRow().
 * Outputs    : buildPlaceLocatorDom() returns every element
 *              createPlaceLocator() wires up or reads (select/useBtn/
 *              pickMapBtn/searchInput/searchBtn/results/status), so the
 *              caller never queries the DOM for them.
 * Constraints: Pure construction, no network, no module state. Every
 *              element is built with createElement/textContent, never raw
 *              markup.
 */
"use strict";

import { t } from "../i18n.js";
import { displayName } from "../state.js";

export function trackerOption(device) {
  const opt = document.createElement("option");
  opt.value = device.device_id;
  opt.textContent = displayName(device) || device.device_id;
  return opt;
}

export function searchResultRow(row, onPick, results) {
  const li = document.createElement("li");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = row.display_name;
  btn.addEventListener("click", () => {
    onPick({ latitude: row.latitude, longitude: row.longitude });
    results.hidden = true;
  });
  li.appendChild(btn);
  return li;
}

function buildTrackerRow() {
  const select = document.createElement("select");
  select.id = "fp-place-tracker-select";
  const useBtn = document.createElement("button");
  useBtn.type = "button";
  // V1: a bare "btn-secondary" only carries background/border, not the
  // padding/radius/cursor that live on .btn -- it read as a plain browser
  // button. .btn-tiny matches this row's compact select+button layout.
  useBtn.className = "btn btn-tiny";
  useBtn.id = "fp-place-use-tracker-btn";
  useBtn.textContent = t("places.field.use");

  const row = document.createElement("div");
  row.className = "fp-dialog-field";
  const label = document.createElement("label");
  label.htmlFor = select.id;
  label.textContent = t("places.field.useTrackerLocation");
  row.append(label, select, useBtn);

  return { row, select, useBtn };
}

/** N13: "click/tap the map to set the center" -- place_locator.js wires this
 * to a caller-supplied callback (places_dialog.js's beginMapPick()) rather
 * than owning the map itself, the same separation the tracker row keeps
 * between "pick a coordinate" and "apply it". */
function buildMapPickRow() {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-tiny";
  btn.id = "fp-place-pick-map-btn";
  btn.textContent = t("places.field.pickOnMap");
  const row = document.createElement("div");
  row.className = "fp-dialog-field";
  row.append(btn);
  return { row, btn };
}

function buildSearchGroup() {
  const searchInput = document.createElement("input");
  searchInput.type = "text";
  searchInput.id = "fp-place-search-input";
  searchInput.placeholder = t("places.search.placeholder");
  const searchBtn = document.createElement("button");
  searchBtn.type = "button";
  searchBtn.className = "btn btn-tiny";
  searchBtn.id = "fp-place-search-btn";
  searchBtn.textContent = t("places.search.button");
  const searchInputRow = document.createElement("div");
  searchInputRow.className = "fp-dialog-field";
  searchInputRow.append(searchInput, searchBtn);

  const results = document.createElement("ul");
  results.id = "fp-place-search-results";
  results.className = "fp-search-results";
  results.hidden = true;
  results.setAttribute("aria-label", t("places.search.resultsLabel"));

  const searchHint = document.createElement("p");
  searchHint.className = "fp-field-hint";
  searchHint.textContent = t("honesty.addressSearch");

  const group = document.createElement("fieldset");
  group.className = "fp-dialog-group";
  const legend = document.createElement("legend");
  legend.textContent = t("places.search.label");
  group.append(legend, searchInputRow, searchHint, results);

  return { group, searchInput, searchBtn, results };
}

/**
 * Build the locator section and mount it into `host`.
 *
 * Pure construction only — createPlaceLocator() in place_locator.js owns
 * every event listener and all behavior.
 */
export function buildPlaceLocatorDom(host) {
  const tracker = buildTrackerRow();
  const mapPick = buildMapPickRow();
  const search = buildSearchGroup();

  const status = document.createElement("p");
  status.className = "fp-field-hint";
  status.id = "fp-place-locator-status";

  host.append(tracker.row, mapPick.row, search.group, status);

  return {
    select: tracker.select,
    useBtn: tracker.useBtn,
    pickMapBtn: mapPick.btn,
    searchInput: search.searchInput,
    searchBtn: search.searchBtn,
    results: search.results,
    status,
  };
}
