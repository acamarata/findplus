/*
 * The day story list: stays and trips as buttons, gaps as quiet markers.
 *
 * Purpose    : One row per stay or trip, in time order, so a day reads as a
 *              story ("Home, Trip to School, School, Trip home ...") instead of
 *              forty near-identical sightings. A stay folds all its sightings
 *              into one line; a long silence between rows gets its own marker.
 * Inputs     : The ordered items from trips_format.js buildItems().
 * Outputs    : An <ol> of rows; markList() and wireStoryKeys() for selection and
 *              the arrow keys.
 * Constraints: Rows are real <button>s. Exactly one is a Tab stop (roving
 *              tabindex); the arrow keys, Home and End move between rows, and
 *              Enter or Space presses the button, which focuses the map on it.
 *              Built with createElement and textContent only.
 */
"use strict";

import { TRIP_COLORS, STAY_COLOR, metaOf, quietOf, rangeText, titleOf } from "./trips_format.js";

function line(cls, text) {
  const el = document.createElement("span");
  el.className = cls;
  el.textContent = text;
  return el;
}

function swatch(item) {
  const dot = document.createElement("span");
  dot.className = `story-dot story-dot--${item.kind}`;
  dot.setAttribute("aria-hidden", "true");
  const color = item.kind === "trip" ? TRIP_COLORS[item.colorIndex] : STAY_COLOR;
  dot.style.setProperty("background", color);
  return dot;
}

function rowButton(item, gaps, onPick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "story-item";
  btn.dataset.id = item.id;
  btn.dataset.kind = item.kind;
  btn.append(swatch(item), line("story-title", titleOf(item)), line("story-when", rangeText(item)), line("story-meta", metaOf(item)));
  const quiet = quietOf(item, gaps);
  if (quiet) btn.appendChild(line("story-quiet", quiet));
  btn.addEventListener("click", () => onPick(item.id));
  return btn;
}

/** The ordered list. `onPick(id)` runs when a row is pressed. */
export function storyList(items, payload, label, onPick) {
  const list = document.createElement("ol");
  list.className = "story-list";
  list.setAttribute("aria-label", label);
  items.forEach((item) => {
    const row = document.createElement("li");
    if (item.kind === "gap") {
      row.className = "story-gap";
      row.textContent = `${titleOf(item)} ${metaOf(item)}`;
    } else {
      row.className = `story-row story-row--${item.kind}`;
      row.appendChild(rowButton(item, payload.gaps, onPick));
    }
    list.appendChild(row);
  });
  return list;
}

const buttons = (root) => [...root.querySelectorAll(".story-item")];

/** Mark the picked row and make it (or the first row) the one Tab stop. */
export function markList(root, id) {
  const all = buttons(root);
  all.forEach((b) => {
    const on = b.dataset.id === id;
    b.classList.toggle("is-picked", on);
    if (on) b.setAttribute("aria-current", "true");
    else b.removeAttribute("aria-current");
  });
  const stop = all.find((b) => b.dataset.id === id) || all[0];
  all.forEach((b) => { b.tabIndex = b === stop ? 0 : -1; });
}

function move(root, from, key) {
  const all = buttons(root);
  const at = all.indexOf(from);
  const next = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: all.length - 1 }[key];
  const target = all[Math.max(0, Math.min(all.length - 1, next))];
  if (!target) return;
  all.forEach((b) => { b.tabIndex = b === target ? 0 : -1; });
  target.focus();
}

/** Wire the arrow keys once on the story host; `onClear` runs for Escape. */
export function wireStoryKeys(root, onClear) {
  root.addEventListener("keydown", (e) => {
    const row = e.target.closest && e.target.closest(".story-item");
    if (!row) return;
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      move(root, row, e.key);
    } else if (e.key === "Escape") {
      onClear();
    }
  });
}
