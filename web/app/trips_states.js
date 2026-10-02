/*
 * The day story's non-happy states: loading, failed, offline, too sparse, empty.
 *
 * Purpose    : Every state of the pane gets words and, where one helps, a button.
 *              A story that cannot be built never looks like a quiet day.
 * Inputs     : Callbacks (retry, switch to the plain list) and the day.
 * Outputs    : DOM nodes the story pane puts in #story.
 * Constraints: Built with createElement and textContent only. Messages are plain
 *              sentences; no stack traces or status codes reach the screen
 *              beyond the server's own one-line reason.
 */
"use strict";

import { paneError } from "./pane_error.js";
import { plural, t } from "./i18n.js";
import { todayLocal } from "./state.js";

/** Grey placeholder rows while the story loads, announced as busy. */
export function skeleton() {
  const note = document.createElement("div");
  note.className = "skeleton";
  note.setAttribute("role", "status");
  note.setAttribute("aria-label", t("common.loading"));
  for (let i = 0; i < 6; i += 1) note.appendChild(document.createElement("i"));
  return note;
}

/** A failed load, with Retry. A dead connection reads differently from a server error. */
export function failure(err, onRetry) {
  if (err && err.offline) {
    return paneError({ title: t("trips.offlineTitle"), message: t("trips.offlineLead"), onRetry });
  }
  return paneError({ title: t("trips.errorTitle"), message: (err && err.message) || "", onRetry });
}

function message(cls, title, lead) {
  const wrap = document.createElement("div");
  wrap.className = "empty empty-state";
  wrap.dataset.story = cls;
  const head = document.createElement("p");
  head.className = "empty-title";
  head.textContent = title;
  const body = document.createElement("p");
  body.className = "empty-lead";
  body.textContent = lead;
  wrap.append(head, body);
  return wrap;
}

/** Sightings exist, but too few to tell a stay from a trip. Offers the plain list. */
export function sparse(count, onRaw) {
  const wrap = message("sparse", t("trips.sparseTitle"), plural("trips.sparseLead", count, { n: count }));
  const row = document.createElement("div");
  row.className = "empty-actions";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn";
  btn.textContent = t("trips.viewRaw");
  btn.addEventListener("click", onRaw);
  row.appendChild(btn);
  wrap.appendChild(row);
  return wrap;
}

/** The heading for a day with no sightings: "No sightings today" or "No sightings on this day". */
export const emptyTitle = (day) => (day === todayLocal() ? t("trips.emptyToday") : t("trips.emptyDay"));

/** The empty message, when the status-aware pane (dashboard_empty.js) has nothing better. */
export const emptyStory = (day) => message("empty", emptyTitle(day), t("trips.emptyLead"));
