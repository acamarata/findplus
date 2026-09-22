/*
 * Place dialog: "Use a tracker's last location" and opt-in address search.
 *
 * Purpose    : Two keyboard-reachable ways to fill a place's coordinates
 *              without a map click (UAT U4/U10): pick a tracked device's
 *              most recent fix, or search an address through the daemon's
 *              own Nominatim proxy. Split out of places_dialog.js so its own
 *              network calls and DOM stay independently testable, the same
 *              way color-picker.js/icon-picker.js are split from the
 *              dialogs that mount them.
 * Inputs     : GET /api/devices for the tracker list (fetched fresh on every
 *              refreshTrackers() rather than trusting `state.devices`, which
 *              may still be empty this early in boot); GET
 *              /api/latest?device_id=; GET /api/places/search?q=.
 * Outputs    : `onPick({ latitude, longitude })`, called whenever either
 *              path resolves a coordinate. Never touches the dialog's own
 *              lat/lon fields directly -- the caller owns those.
 * Constraints: Every element is built with createElement/textContent, never
 *              raw markup. Address search fires only on the Search button or
 *              Enter in its own input -- never on keystroke (R-P2-30.2) --
 *              and Enter is prevented from bubbling to the enclosing
 *              `method="dialog"` form, which would otherwise close the
 *              dialog instead of running the search.
 */
"use strict";

import { api } from "../api.js";
import { t } from "../i18n.js";
import { displayName } from "../state.js";

function trackerOption(device) {
  const opt = document.createElement("option");
  opt.value = device.device_id;
  opt.textContent = displayName(device) || device.device_id;
  return opt;
}

function searchResultRow(row, onPick, results) {
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

/**
 * Build the locator section and mount it into `host`.
 *
 * A factory, not a module singleton (createColorPicker's own shape): the
 * dialog owns exactly one instance, created once in ensureDialog(), and
 * calls `refreshTrackers()`/`reset()` on it rather than rebuilding the DOM
 * every time the dialog opens.
 */
export function createPlaceLocator(host, { onPick }) {
  const select = document.createElement("select");
  select.id = "fp-place-tracker-select";
  const useBtn = document.createElement("button");
  useBtn.type = "button";
  useBtn.className = "btn-secondary";
  useBtn.id = "fp-place-use-tracker-btn";
  useBtn.textContent = t("places.field.use");

  const trackerRow = document.createElement("div");
  trackerRow.className = "fp-dialog-field";
  const trackerLabel = document.createElement("label");
  trackerLabel.htmlFor = select.id;
  trackerLabel.textContent = t("places.field.useTrackerLocation");
  trackerRow.append(trackerLabel, select, useBtn);

  const searchInput = document.createElement("input");
  searchInput.type = "text";
  searchInput.id = "fp-place-search-input";
  searchInput.placeholder = t("places.search.placeholder");
  const searchBtn = document.createElement("button");
  searchBtn.type = "button";
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

  const searchGroup = document.createElement("fieldset");
  searchGroup.className = "fp-dialog-group";
  const searchLegend = document.createElement("legend");
  searchLegend.textContent = t("places.search.label");
  searchGroup.append(searchLegend, searchInputRow, searchHint, results);

  const status = document.createElement("p");
  status.className = "fp-field-hint";
  status.id = "fp-place-locator-status";

  host.append(trackerRow, searchGroup, status);

  function setStatus(text) {
    status.textContent = text;
  }

  function renderResults(rows) {
    results.textContent = "";
    if (!rows.length) {
      const li = document.createElement("li");
      li.className = "fp-search-empty";
      li.textContent = t("places.search.noResults");
      results.appendChild(li);
    } else {
      rows.forEach((row) => results.appendChild(searchResultRow(row, onPick, results)));
    }
    results.hidden = false;
  }

  async function useTrackerLocation() {
    if (!select.value) {
      setStatus(t("places.field.chooseTrackerFirst"));
      return;
    }
    setStatus(t("common.loading"));
    try {
      const fix = await api(`/api/latest?device_id=${encodeURIComponent(select.value)}`);
      onPick({ latitude: fix.latitude, longitude: fix.longitude });
      setStatus("");
    } catch (_) {
      setStatus(t("places.field.noTrackerFix"));
    }
  }

  async function runSearch() {
    const q = searchInput.value.trim();
    if (!q) return;
    setStatus(t("common.loading"));
    searchBtn.disabled = true;
    try {
      const rows = await api(`/api/places/search?q=${encodeURIComponent(q)}`);
      renderResults(rows);
      setStatus("");
    } catch (err) {
      setStatus(t("places.search.failed", { message: err.message }));
    } finally {
      searchBtn.disabled = false;
    }
  }

  useBtn.addEventListener("click", useTrackerLocation);
  searchBtn.addEventListener("click", runSearch);
  searchInput.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    // No type="submit" control exists in this form (Save/Cancel are both
    // type="button"), so Enter would otherwise do nothing useful here and
    // risks a future submit button changing that silently underneath this
    // input -- preventDefault keeps "press Enter to search" from ever also
    // meaning "press Enter to close the dialog".
    e.preventDefault();
    runSearch();
  });

  /** Fetched fresh every call rather than read off `state.devices`: the
   * dialog can open before devices.js's own boot-time load has landed (a
   * fast click right after the map appears), which left this select with
   * only its placeholder option. */
  async function refreshTrackers() {
    while (select.firstChild) select.removeChild(select.firstChild);
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = t("places.field.chooseTracker");
    select.appendChild(placeholder);
    const resp = await api("/api/devices").catch(() => ({ devices: [] }));
    resp.devices.filter((d) => d.is_tracked).forEach((d) => select.appendChild(trackerOption(d)));
  }

  function reset() {
    select.value = "";
    searchInput.value = "";
    results.hidden = true;
    results.textContent = "";
    setStatus("");
  }

  refreshTrackers();

  return { refreshTrackers, reset };
}
