/*
 * Place dialog: "Use a tracker's last location" and opt-in address search.
 *
 * Purpose    : Three keyboard-reachable ways to fill a place's coordinates:
 *              pick a tracked device's most recent fix, click/tap the real
 *              map (UAT6 N13), or search an address through the daemon's own
 *              Nominatim proxy. Split out of places_dialog.js so its own
 *              network calls and DOM stay independently testable, the same
 *              way color-picker.js/icon-picker.js are split from the
 *              dialogs that mount them. DOM construction lives in
 *              place_locator_dom.js (PRI rule-7 50-line function cap, E13
 *              loop-1 follow-up) and each behavior below is its own small
 *              factory for the same reason. The map-pick button itself is
 *              wired here, but starting/ending pick mode is entirely
 *              places_dialog.js's call (`onPickOnMap`): only that module
 *              holds the map, the `<dialog>` and the fields a pick has to
 *              close over, reopen and fill.
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
import { buildPlaceLocatorDom, searchResultRow, trackerOption } from "./place_locator_dom.js";

/** The "use a tracker's last location" half: its own select + button. */
function createTrackerPicker(select, useBtn, { onPick, setStatus }) {
  // UAT2 N5: the dialog's factory ran this once at creation and the dialog's
  // own open handler ran it again, so the two overlapping fetches each
  // cleared-then-appended into the same <select> and every tracker listed
  // twice. A generation token means only the call that is still current when
  // its fetch resolves ever touches the DOM.
  let generation = 0;

  /** Fetched fresh every call rather than read off `state.devices`: the
   * dialog can open before devices.js's own boot-time load has landed (a
   * fast click right after the map appears), which left this select with
   * only its placeholder option. */
  async function refreshTrackers() {
    const mine = ++generation;
    const resp = await api("/api/devices").catch(() => ({ devices: [] }));
    if (mine !== generation) return;
    while (select.firstChild) select.removeChild(select.firstChild);
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = t("places.field.chooseTracker");
    select.appendChild(placeholder);
    resp.devices.filter((d) => d.is_tracked).forEach((d) => select.appendChild(trackerOption(d)));
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
      // UAT2 N8: picking a tracker changed the hidden lat/lon fields with no
      // visible feedback at all. The select's own option text is already the
      // tracker's displayName() (place_locator_dom.js's trackerOption()).
      const name = select.options[select.selectedIndex].textContent;
      setStatus(t("places.field.locationSet", { name }));
    } catch (_) {
      setStatus(t("places.field.noTrackerFix"));
    }
  }

  useBtn.addEventListener("click", useTrackerLocation);
  return { refreshTrackers };
}

/** The opt-in address-search half: its own input, button and results list. */
function createAddressSearch(searchInput, searchBtn, results, { onPick, setStatus }) {
  // UAT2 N8: a pick used to move the hidden lat/lon fields with no visible sign.
  function pickResult(row) {
    onPick({ latitude: row.latitude, longitude: row.longitude });
    setStatus(t("places.field.locationSet", { name: row.display_name }));
  }

  function renderResults(rows) {
    results.textContent = "";
    if (!rows.length) {
      const li = document.createElement("li");
      li.className = "fp-search-empty";
      li.textContent = t("places.search.noResults");
      results.appendChild(li);
    } else {
      rows.forEach((row) =>
        results.appendChild(searchResultRow(row, () => pickResult(row), results)),
      );
    }
    results.hidden = false;
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
}

/**
 * Build the locator section and mount it into `host`.
 *
 * A factory, not a module singleton (createColorPicker's own shape): the
 * dialog owns exactly one instance, created once in ensureDialog(), and
 * calls `refreshTrackers()`/`reset()` on it rather than rebuilding the DOM
 * every time the dialog opens.
 */
export function createPlaceLocator(host, { onPick, onPickOnMap }) {
  const dom = buildPlaceLocatorDom(host);

  function setStatus(text) {
    dom.status.textContent = text;
  }

  const tracker = createTrackerPicker(dom.select, dom.useBtn, { onPick, setStatus });
  createAddressSearch(dom.searchInput, dom.searchBtn, dom.results, { onPick, setStatus });
  if (onPickOnMap) dom.pickMapBtn.addEventListener("click", onPickOnMap);

  function reset() {
    dom.select.value = "";
    dom.searchInput.value = "";
    dom.results.hidden = true;
    dom.results.textContent = "";
    setStatus("");
  }

  tracker.refreshTrackers();

  return { refreshTrackers: tracker.refreshTrackers, reset, showStatus: setStatus };
}
