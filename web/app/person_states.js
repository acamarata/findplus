/*
 * The Person page's non-happy states: loading, empty day, error, offline,
 * partial and "no such person".
 *
 * Purpose    : Every state gets plain words and, where one helps, a button, so a
 *              page that failed never looks like a quiet day.
 * Inputs     : The person's name and callbacks (retry, go back).
 * Outputs    : DOM nodes the page puts in #person-body.
 * Constraints: createElement/textContent only. No coordinates or place names are
 *              built here, so nothing needs purging on lock beyond the node.
 */
"use strict";

import { t } from "./i18n.js";
import { paneError } from "./pane_error.js";
import { skeleton } from "./trips_states.js";
import { todayLocal } from "./state.js";

export function loadingNode(name) {
  const node = skeleton();
  node.setAttribute("aria-label", name ? t("person.loading", { name }) : t("common.loading"));
  return node;
}

function message(kind, title, lead) {
  const wrap = document.createElement("div");
  wrap.className = "empty empty-state";
  wrap.dataset.personState = kind;
  const head = document.createElement("p");
  head.className = "empty-title";
  head.textContent = title;
  const body = document.createElement("p");
  body.className = "empty-lead";
  body.textContent = lead;
  wrap.append(head, body);
  return wrap;
}

/** A day nobody reported on. `name` is the person's. */
export function emptyDayNode(name, day) {
  const title = day === todayLocal() ? t("person.state.emptyToday") : t("person.state.emptyDay");
  return message("empty", title, t("person.state.emptyLead", { name }));
}

/** The person page failed to load: an offline connection reads differently from a server error. */
export function errorNode(name, err, onRetry) {
  if (err && err.offline) {
    return paneError({ title: t("trips.offlineTitle"), message: t("trips.offlineLead"), onRetry });
  }
  return paneError({
    title: t("person.state.errorTitle", { name: name || t("person.kind.person") }),
    message: (err && err.message) || "",
    onRetry,
  });
}

export function notFoundNode() {
  const node = message("notfound", t("person.state.notFoundTitle"), t("person.state.notFoundLead"));
  const link = document.createElement("a");
  link.href = "#";
  link.className = "btn";
  link.textContent = t("person.back");
  node.appendChild(link);
  return node;
}

/** A banner line above a page that loaded only in part. */
export function partialNote(name, failedNames) {
  const p = document.createElement("p");
  p.className = "person-partial";
  p.setAttribute("role", "status");
  p.textContent = t("person.state.partial", { name, names: failedNames.join(", ") });
  return p;
}
