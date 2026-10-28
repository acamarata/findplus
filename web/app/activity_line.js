/*
 * One line of the All Activity feed.
 *
 * Purpose    : Draw a sighting ("5:12 AM · Busy Tag 3 · Home · ±100 m · rough
 *              fix", with the tracker badge and the owner's colour dot and
 *              name) or a person's arrival/departure ("Sam arrived at School").
 * Inputs     : A line from activity_feed.js; onOpen(line) for a sighting click.
 * Outputs    : An <li class="fp-act-line">. A sighting holds one real button
 *              (keyboard reachable); an event line is plain text.
 * Constraints: createElement/textContent only. Colours come from the person
 *              cache, which accepts lowercase #rrggbb only. A suspect sighting
 *              keeps the raw list's faint class and its note.
 */
"use strict";

import { fmtTime } from "./state.js";
import { renderBadge } from "./components/badge.js";
import { button } from "./components/button.js";
import { t } from "./i18n.js";

/** A fix this loose is called rough, as in the raw list. */
const ROUGH_METERS = 100;

const span = (cls, text) => {
  const el = document.createElement("span");
  el.className = cls;
  if (text != null) el.textContent = text;
  return el;
};

function dot(person) {
  const el = span("fp-act-dot");
  el.style.background = person.color;
  el.setAttribute("aria-hidden", "true");
  return el;
}

function accuracyText(point) {
  if (point.accuracy_meters == null) return [t("timeline.accuracyUnknown")];
  const out = [t("activity.accuracy", { meters: Math.round(point.accuracy_meters) })];
  if (point.accuracy_meters >= ROUGH_METERS) out.push(t("timeline.roughFix"));
  return out;
}

/** The text parts after the time, in order; each becomes one " · " piece. */
function pieces(line) {
  const { point, device, person } = line;
  const label = span("fp-act-label");
  label.append(
    renderBadge({ icon: device.icon, color: device.color, label: device.label, name: device.name, size: 20 }),
    span("fp-act-name", line.label)
  );
  const out = [label];
  if (person) {
    const who = span("fp-act-person");
    who.append(dot(person), span("fp-act-person-name", person.name));
    out.push(who);
  }
  if (point.place_name) out.push(span("fp-act-place", point.place_name));
  for (const text of accuracyText(point)) out.push(span("fp-act-meta", text));
  return out;
}

function sightingButton(line, onOpen) {
  const time = fmtTime(line.point.observed_at_local);
  const btn = button({
    label: time, variant: "ghost", size: "xs",
    onClick: () => onOpen(line),
  });
  btn.classList.add("fp-act-btn");
  btn.setAttribute("aria-label", t("activity.openLine", { time, label: line.label }));
  const parts = [span("tl-time", time)];
  for (const piece of pieces(line)) parts.push(document.createTextNode(" · "), piece);
  btn.replaceChildren(...parts);
  return btn;
}

function sightingLine(line, onOpen) {
  const li = document.createElement("li");
  li.className = "fp-act-line tl-item" + (line.point.suspect ? " is-suspect" : "");
  li.dataset.kind = "sighting";
  li.dataset.deviceId = line.deviceId;
  li.dataset.pointId = String(line.point.id);
  li.appendChild(sightingButton(line, onOpen));
  if (line.point.suspect) {
    li.appendChild(span("tl-suspect fp-act-note", line.point.suspect_reason || t("activity.suspectNote")));
  }
  return li;
}

function eventLine(line) {
  const li = document.createElement("li");
  li.className = "fp-act-line fp-act-event";
  li.dataset.kind = "event";
  const key = line.arrived ? "activity.arrived" : "activity.left";
  const row = span("fp-act-row");
  row.append(
    span("tl-time", fmtTime(line.iso)),
    document.createTextNode(" · "),
    dot(line.person),
    span("fp-act-text", t(key, { name: line.person.name, place: line.place }))
  );
  li.appendChild(row);
  return li;
}

/** Build the <li> for one feed line. */
export function renderLine(line, onOpen) {
  return line.kind === "event" ? eventLine(line) : sightingLine(line, onOpen);
}
