/*
 * "Sam's bag looks left at School since 3:00 PM": the dashboard's left-behind notices.
 *
 * Purpose    : Show a tracker that has stayed put while the rest of its person
 *              moved on, in words that admit they are a guess ("looks left"), with
 *              "I know" to say it was on purpose. Only confirmed episodes show here;
 *              a maybe stays on the Person page.
 * Inputs     : GET /api/people and each person's GET /api/people/{id}/left-behind;
 *              POST .../left-behind/{episode}/dismiss for "I know".
 * Outputs    : Rows inside #fp-left-behind; the container is hidden when empty.
 * Constraints: createElement/textContent only. A failed look leaves the rows as
 *              they were. "I know" removes the row at once and puts it back, with the
 *              reason, if the server refuses. purge() empties the rows on lock.
 */
"use strict";

import { t } from "./i18n.js";
import { state } from "./state.js";
import { dismissLeftBehind, fetchLeftBehind, fetchPeople } from "./person_api.js";
import { personLink } from "./person_links.js";

let host = null;
let rows = [];

export function mountLeftBehind(el) {
  host = el;
}

const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

/** The tracker as a person would say it: "bag", or its own name when its role says nothing. */
function thing(person, episode) {
  const tracker = person.trackers.find((x) => x.device_id === episode.device_id);
  const role = tracker && tracker.role;
  return role && role !== "other" ? t(`people.role.${role}`) : episode.device_name;
}

function sentence(person, episode) {
  const vars = { name: person.name, tracker: thing(person, episode), place: episode.place_name, time: clock(episode.started_observed_at) };
  return t(episode.place_name ? "person.leftBehind.row" : "person.leftBehind.rowSpot", vars);
}

function buildRow(person, episode) {
  const row = document.createElement("div");
  row.className = "lb-row";
  row.dataset.episodeId = String(episode.id);
  const text = document.createElement("p");
  text.className = "lb-text";
  text.textContent = sentence(person, episode);
  const note = document.createElement("p");
  note.className = "lb-note";
  note.textContent = t("person.leftBehind.uncertain");
  const know = document.createElement("button");
  know.type = "button";
  know.className = "btn btn-tiny";
  know.textContent = t("person.leftBehind.knowIt");
  know.addEventListener("click", () => onKnow(person, episode, row, know));
  const day = personLink(t("person.leftBehind.seeDay", { name: person.name }), person.id);
  const actions = document.createElement("div");
  actions.className = "lb-actions";
  actions.append(know, day);
  row.append(text, note, actions);
  return row;
}

async function onKnow(person, episode, row, button) {
  button.disabled = true;
  try {
    await dismissLeftBehind(person.id, episode.id);
    row.remove();
    rows = rows.filter((r) => r.episode.id !== episode.id);
    if (!host.children.length) host.hidden = true;
  } catch (err) {
    button.disabled = false;
    if (err.message === "Locked") return;
    const msg = row.querySelector(".lb-error") || row.appendChild(Object.assign(document.createElement("p"), { className: "lb-error" }));
    msg.setAttribute("role", "alert");
    msg.textContent = t("person.leftBehind.dismissFailed", { message: err.message });
  }
}

function draw() {
  host.replaceChildren(...rows.map((r) => buildRow(r.person, r.episode)));
  host.hidden = rows.length === 0;
}

/** Look for confirmed left-behind trackers across everyone and redraw. */
export async function refreshLeftBehind() {
  if (!host || state.locked) return;
  try {
    const people = await fetchPeople();
    const lists = await Promise.all(people.map((p) => fetchLeftBehind(p.id).then((eps) => eps.filter((e) => e.state === "left_behind").map((episode) => ({ person: p, episode })))));
    rows = lists.flat();
    draw();
  } catch (_) { /* offline or locked: keep what is on screen */ }
}

/** Lock purge: no name, tracker or place may stay. */
export function purgeLeftBehind() {
  rows = [];
  if (host) { host.replaceChildren(); host.hidden = true; }
}
