/*
 * Person names that open the Person page, wherever a name is printed.
 *
 * Purpose    : Click "Sam" on a group card, an alert rule sentence, a delivery
 *              row or an arrivals line and land on `#/person/<id>`. One small
 *              module knows who the people are (GET /api/people, cached) and
 *              turns a name inside a piece of text into a real link.
 * Inputs     : The people list; a DOM node whose text may name a person.
 * Outputs    : linkPeople(node), personLink(name, id), personFor(id),
 *              laneLabel(deviceId, trackerName), refreshPeopleCache(),
 *              purgePeopleCache().
 * Constraints: Only whole-word names link, and "Sam" inside a tracker name such
 *              as "Sam Bag" never does (that is a tracker, not the person). Text
 *              is split into text nodes and anchors, never parsed as markup.
 *              Nodes marked `data-person-links` are linked again when the list
 *              arrives late. Nothing here survives a lock (purgePeopleCache).
 */
"use strict";

import { t } from "./i18n.js";
import { fetchPeople } from "./person_api.js";
import { personHref } from "./person_hash.js";
import { state } from "./state.js";

let people = new Map();
let pattern = null;

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const SKIP = "a, button, input, textarea, select, script, style, option, summary";

export const personFor = (id) => people.get(Number(id)) || null;

const ROLES = ["phone", "watch", "collar", "wallet", "keys", "shoes", "bag", "jacket", "bike", "scooter", "tablet", "laptop", "car", "luggage"];

/**
 * The text of a day-story lane: the person's name where the tracker belongs to a
 * person or pet ("Sam", or "Sam (shoes)" when that person has several trackers),
 * else the tracker's own name. A tracker with no known role keeps its own name in
 * brackets, so two lanes of one person never read the same.
 */
export function laneLabel(deviceId, trackerName) {
  const person = [...people.values()].find((p) => (p.trackers || []).some((tr) => tr.device_id === deviceId));
  if (!person) return trackerName;
  if (person.trackers.length < 2) return person.name;
  const own = person.trackers.find((tr) => tr.device_id === deviceId);
  const word = ROLES.includes(own.role) ? t(`people.role.${own.role}`) : trackerName;
  return `${person.name} (${word})`;
}

/** An anchor to a person's page. */
export function personLink(name, id) {
  const a = document.createElement("a");
  a.className = "person-link";
  a.href = personHref(id);
  a.textContent = name;
  a.setAttribute("aria-label", t("person.link", { name }));
  return a;
}

function rebuild(list) {
  people = new Map(list.map((p) => [p.id, p]));
  const names = list.map((p) => p.name).filter(Boolean).sort((a, b) => b.length - a.length);
  pattern = names.length ? new RegExp(`(?<![\\p{L}\\p{N}])(${names.map(escapeRe).join("|")})(?![\\p{L}\\p{N}])`, "gu") : null;
}

/** True when `text` at `index` is really a longer tracker name ("Sam Bag"). */
function isTrackerName(text, index, person) {
  return person.trackers.some((tr) => tr.name.length > person.name.length && tr.name.startsWith(person.name) && text.startsWith(tr.name, index));
}

function splitText(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(pattern)) {
    const person = [...people.values()].find((p) => p.name === m[1]);
    if (!person || isTrackerName(text, m.index, person)) continue;
    if (m.index > last) out.push(document.createTextNode(text.slice(last, m.index)));
    out.push(personLink(m[1], person.id));
    last = m.index + m[1].length;
  }
  if (!out.length) return null;
  if (last < text.length) out.push(document.createTextNode(text.slice(last)));
  return out;
}

/** Link every person's name in the text under `root`. Safe to call again. */
export function linkPeople(root) {
  if (!pattern || !root) return;
  root.dataset.personLinks = "1";
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement && n.parentElement.closest(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((n) => {
    const parts = splitText(n.nodeValue);
    if (parts) n.replaceWith(...parts);
  });
}

/** Mark `node` for linking now and again whenever the people list changes. */
export function markForLinks(node) {
  node.dataset.personLinks = "1";
  linkPeople(node);
  return node;
}

function relinkAll() {
  document.querySelectorAll("[data-person-links]").forEach(linkPeople);
}

/** Reload the people list; every marked node is linked again. A failure keeps the old list. */
export async function refreshPeopleCache() {
  if (state.locked) return;
  try {
    rebuild(await fetchPeople());
    relinkAll();
  } catch (_) { /* offline or locked: names stay plain text */ }
}

/** Lock purge. */
export function purgePeopleCache() {
  people = new Map();
  pattern = null;
}
