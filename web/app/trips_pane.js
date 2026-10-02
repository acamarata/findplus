/*
 * The populated day story: heading, tracker picker, lanes, strip, list, notes.
 *
 * Purpose    : Assemble everything the pane shows once a tracker's trips are
 *              known. trips_view.js owns the state and calls this to build DOM.
 * Inputs     : A context: the tracker, its /api/trips body, the visible
 *              trackers, handlers, and the current selection.
 * Outputs    : One <div class="story-body"> element.
 * Constraints: createElement and textContent only. The honesty sentence under
 *              the list comes from the server's own `label` (honesty.py), with
 *              the bundled catalog copy as the fallback.
 */
"use strict";

import { plural, t } from "./i18n.js";
import { displayName } from "./state.js";
import { uniqueLabel } from "./device_label.js";
import { deviceForTrack } from "./map.js";
import { buildItems, summaryText } from "./trips_format.js";
import { hourStrip } from "./trips_strip.js";
import { storyList } from "./trips_list.js";

/** The tracker's name as every other surface prints it. */
export const nameOf = (track) => uniqueLabel(deviceForTrack(track)) || track.device_name || displayName(track) || track.device_id;

function heading(track) {
  const h = document.createElement("h2");
  h.className = "story-h";
  h.textContent = t("trips.storyFor", { name: nameOf(track) });
  return h;
}

/** "Whose day?" select, only when the Show filter is on All and several trackers have sightings. */
function picker(ctx) {
  const wrap = document.createElement("div");
  wrap.className = "story-pick";
  const label = document.createElement("label");
  label.htmlFor = "story-pick";
  label.textContent = t("trips.pickLabel");
  const select = document.createElement("select");
  select.id = "story-pick";
  ctx.list.forEach((tr) => {
    const opt = document.createElement("option");
    opt.value = tr.device_id;
    opt.textContent = nameOf(tr);
    opt.selected = tr.device_id === ctx.track.device_id;
    select.appendChild(opt);
  });
  select.addEventListener("change", () => ctx.onPickDevice(select.value));
  wrap.append(label, select);
  return wrap;
}

function note(cls, text) {
  const p = document.createElement("p");
  p.className = cls;
  p.textContent = text;
  return p;
}

/** The checkbox that brings the folded sightings back onto the map. */
function insideToggle(ctx) {
  const label = document.createElement("label");
  label.className = "toggle story-inside";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.id = "story-inside";
  box.checked = ctx.showInside;
  box.addEventListener("change", () => ctx.onInside(box.checked));
  const span = document.createElement("span");
  span.textContent = t("trips.showInside");
  label.append(box, span);
  return label;
}

/** Everything under the heading for one tracker's day. */
export function storyBody(ctx) {
  const body = document.createElement("div");
  body.className = "story-body";
  const items = buildItems(ctx.payload);
  body.appendChild(heading(ctx.track));
  if (ctx.list.length > 1 && !ctx.fixedDevice) body.appendChild(picker(ctx));
  const slot = document.createElement("div");
  slot.className = "lanes-slot";
  body.appendChild(slot);
  body.append(note("story-summary", summaryText(ctx.payload)), hourStrip(ctx.payload, ctx.day, ctx.onPick));
  body.appendChild(storyList(items, ctx.payload, t("trips.listLabel"), ctx.onPick));
  const n = ctx.payload.outliers.length;
  if (n) body.appendChild(note("story-stray", plural("trips.strays", n, { n })));
  body.append(note("story-fold", t("trips.foldNote")), insideToggle(ctx));
  body.appendChild(note("notice small story-honesty", ctx.payload.label || t("honesty.tripsApproximate")));
  return body;
}
