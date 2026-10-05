/*
 * The Person page header: avatar, name, the "where now" sentence, how sure it
 * is, and how long ago anything was seen.
 *
 * Purpose    : Answer "where is Sam?" in plain words, never as a fact: the
 *              sentence is the server's own (likely, probably, not sure, no
 *              recent sighting), and the chip repeats how sure it is.
 * Inputs     : The person (GET /api/people/{id}) and their now answer
 *              (GET /api/people/{id}/now), either of which may be missing.
 * Outputs    : Fills #person-head.
 * Constraints: textContent only. NOW is for today only: a past day reads "On <date>". The "seen N min ago" chip is shown only when
 *              the server gave an age. A pet reads "Pet" beside its name.
 */
"use strict";

import { $, fmtAgeMinutes } from "./state.js";
import { t } from "./i18n.js";
import { personAvatarButton } from "./person_avatar.js";

const CONFIDENCE = ["likely", "probably", "unsure", "unknown"];

function chip(cls, text) {
  const el = document.createElement("span");
  el.className = `person-chip ${cls}`;
  el.textContent = text;
  return el;
}

/** "Sep 30, 2026" for a YYYY-MM-DD day. */
function dayLabel(date) {
  return new Date(`${date}T12:00:00Z`).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

/** After an edit from the avatar: reload the page in place (dynamic import: person_page imports this file). */
const reloadPage = async () => (await import("./person_page.js")).reload();

/** For a past day: "On Sep 30, 2026: At Home from 3:40 PM." Never the live "now" answer. */
function pastText(past) {
  const when = dayLabel(past.date);
  return past.last ? t("person.head.onDateLast", { date: when, last: past.last }) : t("person.head.onDate", { date: when });
}

function statusLine(now, past) {
  const p = document.createElement("p");
  p.className = "person-now";
  p.id = "person-now";
  p.textContent = past ? pastText(past) : now ? now.text : "";
  return p;
}

/** The "Likely" / "Probably" / "Unsure" / "Unknown" pill; the Latest rows reuse it. */
export function confidenceChip(confidence) {
  const level = CONFIDENCE.includes(confidence) ? confidence : "unknown";
  return chip(`person-conf person-conf--${level}`, t(`person.conf.${level}`));
}

function chips(now) {
  const row = document.createElement("p");
  row.className = "person-chips";
  if (!now) return row;
  row.appendChild(confidenceChip(now.confidence));
  const age = now.age_minutes;
  const seen = typeof age === "number" ? t("person.seenAgo", { age: fmtAgeMinutes(age) }) : t("person.neverSeen");
  row.appendChild(chip("person-seen", seen));
  return row;
}

/**
 * Fill the header. `person` is required; `now` may be null (not loaded or failed).
 * `past` is {date, last} when a day before today is on screen: the header then
 * says what that day ended with, and carries no "seen N min ago" chip.
 */
export function renderHead(person, now, past = null) {
  const head = $("person-head");
  const badge = document.createElement("span");
  badge.className = "person-avatar";
  // The avatar is a button: Edit person opens at the icon and colour pickers (dashboard 1.3).
  const avatar = personAvatarButton(person, { size: 44, onSaved: reloadPage });
  avatar.id = "person-avatar";
  badge.appendChild(avatar);
  const name = document.createElement("h2");
  name.className = "person-name";
  name.id = "person-name";
  name.tabIndex = -1;
  name.textContent = person.name;
  if (person.kind === "pet") name.appendChild(chip("person-kind", t("person.kind.pet")));
  const text = document.createElement("div");
  text.className = "person-head-text";
  text.append(name, statusLine(now, past), chips(past ? null : now));
  head.replaceChildren(badge, text);
}

export function clearHead() {
  $("person-head").replaceChildren();
}
