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
import { labelMap } from "../device_label.js";

/** `labels` is device_label.js's labelMap() of the list this select shows. */
export function trackerOption(device, labels = labelMap([device])) {
  const opt = document.createElement("option");
  opt.value = device.device_id;
  opt.textContent = labels.get(device.device_id) || displayName(device) || device.device_id;
  return opt;
}

/** One option per tracked device, labelled apart where names clash (UAT #7). A
 * tracker never seen is marked: asking /api/latest for it would answer 404,
 * which the browser logs as a console error (UAT #20). */
export function appendTrackerOptions(select, tracked) {
  const labels = labelMap(tracked);
  tracked.forEach((d) => {
    const opt = trackerOption(d, labels);
    if (!d.observation_count) opt.dataset.noFix = "1";
    select.appendChild(opt);
  });
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

/** U5: "Use map centre" and "Pick on map" work on the live map beside the sheet.
 * place_locator.js wires both to callbacks the place sheet supplies (it owns the
 * map and the fields); both rows are hidden when the map is not on screen
 * (the sheet then opens as a plain dialog: `.fp-map-only`). */
function buildMapPickRow() {
  const centreBtn = document.createElement("button");
  centreBtn.type = "button";
  centreBtn.className = "btn btn-tiny";
  centreBtn.id = "fp-place-use-centre-btn";
  centreBtn.textContent = t("places.field.useMapCentre");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-tiny";
  btn.id = "fp-place-pick-map-btn";
  btn.setAttribute("aria-pressed", "false");
  btn.textContent = t("places.field.pickOnMap");
  const row = document.createElement("div");
  row.className = "fp-dialog-field fp-map-only fp-place-mapbtns";
  row.append(centreBtn, btn);
  return { row, btn, centreBtn };
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

  host.append(mapPick.row, search.group, tracker.row, status);

  return {
    select: tracker.select,
    useBtn: tracker.useBtn,
    pickMapBtn: mapPick.btn,
    centreBtn: mapPick.centreBtn,
    searchInput: search.searchInput,
    searchBtn: search.searchBtn,
    results: search.results,
    status,
  };
}
