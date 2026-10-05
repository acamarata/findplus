/*
 * Latest pane (the default side-panel tab): where everyone and everything is now.
 *
 * Purpose    : One list. People first (alphabetical): avatar, name, the person
 *              engine's "where" sentence, a confidence pill, their tracker badges;
 *              stale people are dimmed. Then the trackers that belong to no person,
 *              most recent first: badge, label, place or "Not at a saved place", and
 *              "seen 7 min ago". A person row opens the Person page (#/person/<id>); a
 *              tracker row focuses that tracker (tracker_focus.js). Each row has an
 *              Edit icon button (person editor / device editor).
 * Inputs     : mountLatest(container): container is #tab-latest. Data comes from
 *              latest_data.js. Events: findplus:data-refreshed (via refreshLatest),
 *              findplus:people-changed.
 * Outputs    : DOM inside the container; the left-behind chips (#fp-left-behind)
 *              sit above the list (the suggestions banner stays in People).
 * Constraints: mountLatest is idempotent and runs each time the tab is shown. While a
 *              tracker is focused the tab shows the focus view instead of the list.
 *              createElement/textContent only. purgeLatest() empties it on lock.
 */
"use strict";

import { t } from "./i18n.js";
import { state } from "./state.js";
import { personHref } from "./person_hash.js";
import { loadLatest } from "./latest_data.js";
import { personRow, trackerRow, openDeviceEditor } from "./latest_rows.js";
import { structure, drawList } from "./tracker_focus_view.js";
import { dropFocus, focusTracker, showFocusIfActive } from "./tracker_focus.js";

let seq = 0;
let wired = false;

function emptyState() {
  const wrap = document.createElement("div");
  wrap.className = "empty empty-state fp-latest-empty";
  const title = document.createElement("p");
  title.className = "empty-title";
  title.textContent = t("latest.emptyTitle");
  const lead = document.createElement("p");
  lead.className = "empty-lead";
  lead.textContent = t("latest.emptyLead");
  const link = document.createElement("a");
  link.className = "fp-btn fp-btn--primary";
  link.href = "#/setup";
  link.textContent = t("latest.emptyAction");
  wrap.append(title, lead, link);
  return wrap;
}

const refreshSoon = () => { refreshLatest(); };

function personEdit(person) {
  return async () => {
    const { openPersonEditor } = await import("./person_editor.js");
    await openPersonEditor(person.id, () => window.dispatchEvent(new CustomEvent("findplus:people-changed")));
  };
}

function build(data) {
  const ul = document.createElement("ul");
  ul.className = "fp-latest-rows";
  const devices = state.devices || [];
  data.people.forEach((entry) => ul.appendChild(personRow(entry, {
    devices,
    onOpen: () => { window.location.hash = personHref(entry.person.id); },
    onEdit: personEdit(entry.person),
  })));
  data.trackers.forEach((device) => ul.appendChild(trackerRow(device, {
    onOpen: () => focusTracker(device.device_id),
    onEdit: () => openDeviceEditor(device, refreshSoon),
  })));
  return ul;
}

/** Redraw the list from fresh data; a slower, older answer never overwrites a newer one. */
async function draw(container) {
  const mine = ++seq;
  const gen = state.lockGeneration;
  const data = await loadLatest();
  if (mine !== seq || gen !== state.lockGeneration || state.locked) return;
  const { list } = structure(container);
  const empty = !data.people.length && !data.trackers.length;
  list.setAttribute("aria-label", t("latest.listLabel"));
  list.replaceChildren(empty ? emptyState() : build(data));
}

/** Left-behind chips sit above the list; the suggestions banner belongs to People (spec). */
function adoptBanners(container) {
  const el = document.getElementById("fp-left-behind");
  if (el && el.parentElement !== container) container.prepend(el);
}

export function mountLatest(container) {
  if (!wired) {
    wired = true;
    window.addEventListener("findplus:people-changed", () => { if (isShown()) refreshLatest(); });
  }
  structure(container);
  adoptBanners(container);
  if (showFocusIfActive()) return Promise.resolve();
  drawList(container);
  return draw(container);
}

const isShown = () => { const c = document.getElementById("tab-latest"); return Boolean(c && !c.hidden); };

export function refreshLatest() {
  const container = document.getElementById("tab-latest");
  if (!container || container.hidden || container.querySelector("#fp-latest-focus:not([hidden])")) return Promise.resolve();
  return draw(container);
}

/** Lock purge: no name, place or time may stay in the list. */
export function purgeLatest() {
  seq += 1;
  dropFocus();
  const list = document.getElementById("fp-latest-list");
  if (list) list.replaceChildren();
}
