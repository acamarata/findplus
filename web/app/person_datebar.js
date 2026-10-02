/*
 * The Person page's date bar: previous and next arrows, a date picker, Today,
 * and the left/right arrow keys.
 *
 * Purpose    : Move through a person's days without leaving the page. Every move
 *              rewrites the hash (`#/person/<id>?date=...`), so the browser's Back
 *              button steps through the days and a day can be bookmarked.
 * Inputs     : The current person id and day; the controls from partials/person.html.
 * Outputs    : A hash change. main.js's hashchange handler re-renders the page.
 * Constraints: The next arrow and the picker stop at today: nothing has been
 *              seen in the future. Arrow keys are ignored while a form control
 *              or dialog has focus, and with a modifier held.
 */
"use strict";

import { $, todayLocal } from "./state.js";
import { personHref } from "./person_hash.js";

let current = { id: null, date: null };

/** `date` moved by `days` calendar days, as YYYY-MM-DD (no time zone maths: dates only). */
export function shiftDay(date, days) {
  const d = new Date(`${date}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function go(date) {
  if (!current.id || !date || date > todayLocal()) return;
  window.location.hash = personHref(current.id, date);
}

/** Show `date` in the controls and enable or disable what cannot go further. */
export function syncDateBar(id, date) {
  current = { id, date };
  const today = todayLocal();
  $("person-date").value = date;
  $("person-date").max = today;
  $("person-next").disabled = date >= today;
  $("person-today").disabled = date === today;
}

function typing(target) {
  return target && (target.closest("input, select, textarea, dialog[open]") || target.isContentEditable);
}

function onKey(event) {
  const panel = $("tab-person");
  if (!panel || panel.hidden || event.altKey || event.ctrlKey || event.metaKey) return;
  if (typing(event.target) || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  go(shiftDay(current.date, event.key === "ArrowLeft" ? -1 : 1));
}

/** Wire the buttons, the picker and the keys once. */
export function wireDateBar() {
  $("person-prev").addEventListener("click", () => go(shiftDay(current.date, -1)));
  $("person-next").addEventListener("click", () => go(shiftDay(current.date, 1)));
  $("person-today").addEventListener("click", () => go(todayLocal()));
  $("person-date").addEventListener("change", (e) => go(e.target.value));
  document.addEventListener("keydown", onKey);
}
