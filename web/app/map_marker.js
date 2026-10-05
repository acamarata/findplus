/*
 * Map marker icons: a tracker's own badge, optionally ringed in its person's colour.
 *
 * Purpose    : Split out of map.js (300-line cap) and extended for dashboard 1.3:
 *              a tracker that belongs to a person (or pet) gets a ring in that
 *              person's colour around its badge. The badge colour inside is the
 *              tracker's own and never changes.
 * Inputs     : A tracker (device row), optionally a person {name, color} from
 *              person_colours.js, and for numbered markers the point and its place
 *              in the track.
 * Outputs    : Leaflet divIcons; markerTitle() for the hover title.
 * Constraints: The ring is decoration (aria-hidden SVG, colour as a presentation
 *              attribute because CSP drops inline style=""). The person is named in
 *              the marker's title and in the popup, never by colour alone. Only a
 *              validated lowercase #rrggbb reaches the markup.
 * Reuse      : map.js (tracks and first-run markers).
 */
"use strict";

import { renderBadge } from "./components/badge.js";
import { t } from "./i18n.js";

const HEX = /^#[0-9a-f]{6}$/;

/** The ring markup for a person's colour, or "" when there is no person or no valid colour. */
export function ringHtml(person) {
  if (!person || !HEX.test(person.color || "")) return "";
  return (
    // 2 px surface-coloured gap (class, so the theme picks the colour) then a 3 px person-colour
    // ring: when the person's colour equals the tracker's the gap still keeps the ring readable.
    '<svg class="marker-ring" width="36" height="36" viewBox="0 0 36 36" aria-hidden="true" focusable="false">' +
    '<circle class="marker-ring-gap" cx="18" cy="18" r="14" fill="none" stroke-width="2"/>' +
    `<circle class="marker-ring-person" cx="18" cy="18" r="16.5" fill="none" stroke="${person.color}" stroke-width="3"/></svg>`
  );
}

function badgeHtml(device) {
  return renderBadge({
    icon: device.icon, color: device.color, label: device.label, name: device.name, size: 26,
  }).outerHTML;
}

/** The hover title: the tracker's name, plus whose it is when it belongs to a person. */
export function markerTitle(shown, person) {
  return person ? t("personColours.markerTitle", { tracker: shown, name: person.name }) : shown;
}

/**
 * Show or hide the sighting numbers on the markers. They mean "order of this
 * tracker's sightings", so they are off by default (a marker shows its tracker's
 * badge) and a focused Every-sighting view turns them on.
 */
export function setSightingNumbers(map, on) {
  map.getContainer().classList.toggle("map--numbered", Boolean(on));
}

/** One tracker's latest-position marker (no number, no track). */
export function trackerIcon(device, person) {
  return L.divIcon({
    className: "",
    html:
      `<div class="marker-num${person ? " marker-num--ringed" : ""}">${ringHtml(person)}` +
      `<span class="marker-num-glyph">${badgeHtml(device)}</span></div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

/**
 * The numbered marker for one point, in its device's colour and icon.
 *
 * The number is the point's order within its track, not its identity, so it
 * stays; the flat background behind it becomes the device's badge. `device` is
 * resolved by the caller, which keeps this function free of any state lookup.
 *
 * This is the one place in the app that reads a badge as markup:
 * `L.divIcon({ html })` takes a string, not a node (specs/labels-and-icons.md
 * § Rendering). Every other caller appends the live SVGElement.
 */
export function numberedIcon(point, index, total, device, person = null) {
  const classes = ["marker-num"];
  if (!point.is_movement) classes.push("jitter");
  if (point.suspect) classes.push("marker-num--suspect");
  if (person) classes.push("marker-num--ringed");
  // first/last are the only two non-default borders; components.css owns the colours
  // (an inline style="border-color:..." is dropped by CSP, UAT U25).
  if (index === 0) classes.push("marker-num--first");
  else if (index === total - 1) classes.push("marker-num--last");
  const glyph = point.is_movement ? badgeHtml(device) : "";
  return L.divIcon({
    className: "",
    html:
      `<div class="${classes.join(" ")}">${ringHtml(person)}` +
      `<span class="marker-num-glyph">${glyph}</span>` +
      `<span class="marker-num-seq">${point.sequence}</span></div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}
