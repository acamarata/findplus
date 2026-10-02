/*
 * The day summary card on the Person page: "7:40 AM left Home", "8:10 AM arrived
 * at School", one line each, in the server's own words.
 *
 * Purpose    : Tell the day as a short list. Each line is a button: selecting it
 *              moves the map and the day story to that moment.
 * Inputs     : normalizeDay() output (person_api.js), the person's name and
 *              callbacks `onFocus(line)` and `onShowSuspect()`.
 * Outputs    : One <section class="person-card">.
 * Constraints: textContent only. The server wrote the sentences (including
 *              "around" and "No sightings" wording); this file never rewrites a
 *              time. When the summary could not be fetched the card says so and
 *              the rest of the page still works.
 */
"use strict";

import { plural, t } from "./i18n.js";

function lineButton(line, onFocus) {
  const li = document.createElement("li");
  li.className = "person-line";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "person-line-btn";
  btn.dataset.lineId = String(line.id);
  const text = document.createElement("span");
  text.className = "person-line-text";
  text.textContent = line.text;
  btn.appendChild(text);
  if (line.via) {
    const via = document.createElement("span");
    via.className = "person-line-via";
    via.textContent = t("person.summary.via", { via: line.via });
    btn.appendChild(via);
  }
  btn.addEventListener("click", () => onFocus(line));
  li.appendChild(btn);
  return li;
}

function note(cls, text) {
  const p = document.createElement("p");
  p.className = cls;
  p.textContent = text;
  return p;
}

function card(title) {
  const section = document.createElement("section");
  section.className = "person-card person-summary";
  section.setAttribute("aria-labelledby", "person-summary-title");
  const h = document.createElement("h3");
  h.id = "person-summary-title";
  h.className = "person-card-title";
  h.textContent = title;
  section.appendChild(h);
  return section;
}

/** Mark the line the person picked (called by the page after a focus). */
export function markLine(root, id) {
  root.querySelectorAll(".person-line-btn").forEach((b) => {
    const on = b.dataset.lineId === String(id);
    b.classList.toggle("is-picked", on);
    if (on) b.setAttribute("aria-current", "true");
    else b.removeAttribute("aria-current");
  });
}

/** "2 sightings looked wrong and were left out (show)": the server's sentence plus a Show button. */
function suspectNote(day, onShow) {
  const p = note("person-note person-suspect-note", day.suspectText || plural("person.summary.wrong", day.suspectCount, { n: day.suspectCount }));
  const show = document.createElement("button");
  show.type = "button";
  show.className = "btn btn-tiny person-suspect-show";
  show.textContent = t("person.summary.showWrong");
  show.addEventListener("click", onShow);
  p.append(" ", show);
  return p;
}

/** The summary card. `day` is null when the summary failed to load. */
export function summaryCard(name, day, onFocus, onShowSuspect) {
  const section = card((day && day.heading) || t("person.summary.title", { name }));
  if (!day) {
    section.appendChild(note("person-note", t("person.summary.unavailable")));
    return section;
  }
  if (!day.lines.length) {
    section.appendChild(note("person-note", t("person.summary.noLines")));
  } else {
    const list = document.createElement("ul");
    list.className = "person-lines";
    day.lines.forEach((line) => list.appendChild(lineButton(line, onFocus)));
    section.append(note("person-hint", t("person.summary.hint")), list);
  }
  if (day.suspectCount) section.appendChild(suspectNote(day, onShowSuspect));
  section.appendChild(note("notice small person-honesty", day.label || t("honesty.tripsApproximate")));
  return section;
}
