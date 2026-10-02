/*
 * The day's time bars: the hour strip above the story and the family lanes.
 *
 * Purpose    : Show at a glance where the time went. The strip is one bar from
 *              midnight to midnight for the chosen tracker: stays in slate, each
 *              trip in its own colour, gaps left empty. The lanes put one such
 *              bar per group member under each other, stays coloured by place,
 *              so "who was where, and when" reads straight down.
 * Inputs     : Story items (trips_format.js buildItems) and the day's date.
 * Outputs    : DOM nodes (SVG bars with a text label), never markup strings.
 * Constraints: Presentation attributes only (x, width, fill): CSP blocks inline
 *              style. Bars carry <title> text for pointer hover; the keyboard
 *              path is the story list, so the strip itself is not a Tab stop.
 */
"use strict";

import { plural, t } from "./i18n.js";
import { TRIP_COLORS, STAY_COLOR, buildItems, minuteOfDay, placeColor, rangeText, titleOf } from "./trips_format.js";

const NS = "http://www.w3.org/2000/svg";
const DAY_MINUTES = 1440;
const MOVING = TRIP_COLORS[0];

/** An SVG <rect> for one item, with a hover title and (optionally) its id. */
function rect(item, day, fill) {
  const from = minuteOfDay(item.start_local, day);
  const to = minuteOfDay(item.end_local, day);
  const r = document.createElementNS(NS, "rect");
  r.setAttribute("x", String(from));
  r.setAttribute("width", String(Math.max(to - from, 6)));
  r.setAttribute("y", "0");
  r.setAttribute("height", "20");
  r.setAttribute("rx", "3");
  r.setAttribute("fill", fill);
  r.dataset.id = item.id;
  const title = document.createElementNS(NS, "title");
  title.textContent = `${titleOf(item)}, ${rangeText(item)}`;
  r.appendChild(title);
  return r;
}

function barSvg(items, day, fillOf) {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${DAY_MINUTES} 20`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("class", "strip-bar");
  svg.setAttribute("aria-hidden", "true");
  items.filter((i) => i.kind !== "gap").forEach((i) => svg.appendChild(rect(i, day, fillOf(i))));
  return svg;
}

/** Four tick labels (midnight, 6, noon, 18, midnight) under a bar. */
function ticks() {
  const row = document.createElement("div");
  row.className = "strip-ticks";
  row.setAttribute("aria-hidden", "true");
  [0, 6, 12, 18, 24].forEach((h) => {
    const s = document.createElement("span");
    s.textContent = new Date(2000, 0, 1, h % 24).toLocaleTimeString([], { hour: "numeric" });
    row.appendChild(s);
  });
  return row;
}

const tripFill = (i) => (i.kind === "trip" ? TRIP_COLORS[i.colorIndex] : STAY_COLOR);

/** The strip for one tracker. `onPick(id)` runs when a bar is clicked. */
export function hourStrip(payload, day, onPick) {
  const items = buildItems(payload);
  const wrap = document.createElement("div");
  wrap.className = "strip";
  wrap.setAttribute("role", "img");
  wrap.setAttribute("aria-label", t("trips.stripLabel", {
    stays: plural("trips.stays", payload.stays.length, { n: payload.stays.length }),
    trips: plural("trips.trips", payload.trips.length, { n: payload.trips.length }),
  }));
  const svg = barSvg(items, day, tripFill);
  svg.addEventListener("click", (e) => {
    const id = e.target.dataset && e.target.dataset.id;
    if (id) onPick(id);
  });
  wrap.append(svg, ticks());
  return wrap;
}

/** Mark one bar as the picked item (called by the view after a selection). */
export function markStrip(root, id) {
  root.querySelectorAll(".strip-bar rect").forEach((r) => r.classList.toggle("is-picked", r.dataset.id === id));
}

const laneFill = (i) => (i.kind === "trip" ? MOVING : placeColor(i));

function laneRow(member, day, active, actions) {
  const row = document.createElement("li");
  row.className = "lane";
  const name = document.createElement("button");
  name.type = "button";
  name.className = "lane-name";
  name.setAttribute("aria-pressed", String(active));
  name.textContent = member.name;
  name.addEventListener("click", () => actions.onMember(member.device_id));
  row.appendChild(name);
  if (member.payload) row.appendChild(barSvg(buildItems(member.payload), day, laneFill));
  else row.appendChild(laneNote(member, actions));
  return row;
}

/** A lane that is still loading, or failed (with its own Retry). */
function laneNote(member, actions) {
  const note = document.createElement("span");
  note.className = "lane-note";
  if (member.failed) {
    note.textContent = t("trips.laneFailed");
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "btn btn-tiny";
    retry.textContent = t("common.retry");
    retry.addEventListener("click", () => actions.onRetry(member.device_id));
    note.appendChild(retry);
  } else {
    note.textContent = t("common.loading");
  }
  return note;
}

/** The distinct places seen across the lanes, each with its colour. */
function legend(members) {
  const seen = new Map();
  members.forEach((m) => (m.payload ? m.payload.stays : []).forEach((s) => {
    if (s.place_id != null) seen.set(s.place_id, { name: s.label, color: placeColor(s) });
  }));
  const list = document.createElement("ul");
  list.className = "lane-legend";
  const chip = (text, color) => {
    const li = document.createElement("li");
    const sw = document.createElement("span");
    sw.className = "lane-chip";
    sw.style.setProperty("background", color);
    li.append(sw, document.createTextNode(text));
    list.appendChild(li);
  };
  seen.forEach(({ name, color }) => chip(name, color));
  chip(t("trips.legendUnnamed"), placeColor({ place_id: null }));
  chip(t("trips.legendMoving"), MOVING);
  return list;
}

/** Family lanes: `members` is [{device_id, name, payload|null, failed}]. */
export function lanes(members, day, activeId, actions) {
  const box = document.createElement("section");
  box.className = "lanes";
  const head = document.createElement("h3");
  head.className = "story-sub";
  head.textContent = t("trips.lanesTitle");
  const list = document.createElement("ul");
  list.className = "lane-list";
  list.setAttribute("aria-label", t("trips.lanesTitle"));
  members.forEach((m) => list.appendChild(laneRow(m, day, m.device_id === activeId, actions)));
  const scale = ticks();
  scale.classList.add("lane-scale");
  box.append(head, list, scale, legend(members));
  return box;
}
