/*
 * Places tab: search and sort for the side-panel list.
 *
 * Purpose    : Past a handful of places the list needs a way to find one. A
 *              search box (matches the name) and a sort choice (name, newest,
 *              biggest) sit above it once there are two or more places.
 * Inputs     : The places array from GET /api/places.
 * Outputs    : buildTools(onChange) -> the toolbar element (kept between
 *              refreshes so typing is never interrupted); applyTools(places)
 *              -> the filtered, sorted array; toolsVisible(count).
 * Constraints: textContent only. Query and sort live in module state only, they
 *              are never saved (a place name is location data, so nothing here
 *              survives a lock, see reset()).
 */
"use strict";

import { t } from "./i18n.js";

const SORTS = ["name", "newest", "radius"];
let query = "";
let sort = "name";
let toolbar = null;

/** The toolbar, built once; `onChange` re-renders the list. */
export function buildTools(onChange) {
  if (toolbar) return toolbar;
  toolbar = document.createElement("div");
  toolbar.className = "fp-places-tools";
  toolbar.hidden = true;

  const search = document.createElement("input");
  search.type = "search";
  search.id = "fp-places-search";
  search.placeholder = t("places.tools.searchPlaceholder");
  search.setAttribute("aria-label", t("places.tools.searchLabel"));
  search.addEventListener("input", () => {
    query = search.value;
    onChange();
  });

  const select = document.createElement("select");
  select.id = "fp-places-sort";
  select.setAttribute("aria-label", t("places.tools.sortLabel"));
  SORTS.forEach((key) => {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = t(`places.tools.sort.${key}`);
    select.appendChild(opt);
  });
  select.addEventListener("change", () => {
    sort = select.value;
    onChange();
  });

  toolbar.append(search, select);
  return toolbar;
}

/** Only worth showing once there is something to search. */
export function toolsVisible(count) {
  if (toolbar) toolbar.hidden = count < 2;
}

/** `places`, narrowed by the search text and ordered by the chosen sort. */
export function applyTools(places) {
  const q = query.trim().toLowerCase();
  const kept = q ? places.filter((p) => p.name.toLowerCase().includes(q)) : [...places];
  const order = {
    name: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
    newest: (a, b) => new Date(b.created_at) - new Date(a.created_at) || b.id - a.id,
    radius: (a, b) => b.radius_meters - a.radius_meters,
  };
  return kept.sort(order[sort]);
}

export function activeQuery() {
  return query.trim();
}

/** Forget the search and sort (the lock hook). */
export function reset() {
  query = "";
  sort = "name";
  if (toolbar) {
    toolbar.querySelector("input").value = "";
    toolbar.querySelector("select").value = "name";
    toolbar.hidden = true;
  }
}
