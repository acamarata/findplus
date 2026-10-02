/*
 * The Person page's hash route: `#/person/<id>?date=YYYY-MM-DD`.
 *
 * Purpose    : One place that reads and writes the route, so main.js, the date
 *              bar and every "click a name" link agree on its shape.
 * Inputs     : A location hash, or a person id and an optional day.
 * Outputs    : personRoute(hash) -> {id, date} | null, personHref(id, date).
 * Constraints: Pure and synchronous (main.js calls it on every hashchange).
 *              A malformed date is dropped, never passed on to the server.
 */
"use strict";

const ROUTE = /^#\/person\/(\d+)(?:\?(.*))?$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** `{id, date}` for a person hash (date null when absent or malformed), else null. */
export function personRoute(hash) {
  const m = ROUTE.exec(hash || "");
  if (!m) return null;
  const date = new URLSearchParams(m[2] || "").get("date");
  return { id: Number(m[1]), date: date && DAY.test(date) ? date : null };
}

/** The hash for a person, with a day when one is given. */
export function personHref(id, date) {
  return `#/person/${id}${date ? `?date=${date}` : ""}`;
}
