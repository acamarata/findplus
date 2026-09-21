/*
 * Onboarding step 5 — Places (optional).
 *
 * Purpose    : List the geofences that exist and offer the same click-the-map
 *              flow places_dialog.js already implements, rather than a second
 *              copy of it (specs/onboarding.md § 4 row 5).
 * Inputs     : ctx.api / ctx.state, handed down by the Wizard.
 * Outputs    : DOM inside the step container. Saving a place is
 *              places_dialog.js's own POST /api/places, untouched here.
 * Constraints: Skip is a true no-op. The map is the one Leaflet instance
 *              state.map already holds: this step borrows the element while it
 *              is on screen and hands it back in onLeave, never building a
 *              second map. The dashboard's "Observed path" disclaimer rides
 *              along inside `.map-pane` (it is a sibling of `#map`, not a
 *              child); it is hidden for the duration, since a first-run,
 *              near-empty map has no observed path for the sentence to
 *              describe (visual gate W4 F3).
 */
"use strict";

import { t } from "../i18n.js";
import { activateCrosshairMode } from "../places_dialog.js";

/** Where `.map-pane` came from, so onLeave can put it back exactly there. */
let borrowed = null;
let els = null;

/**
 * Move the shared map into the step, remembering where it was.
 *
 * #app-shell is hidden while the wizard is open, so the map has to come to the
 * wizard for the crosshair click to be reachable at all.
 */
function borrowMap(host) {
  const pane = document.querySelector(".map-pane");
  if (!pane || borrowed) return;
  borrowed = { parent: pane.parentNode, before: pane.nextSibling, pane };
  const disclaimer = document.getElementById("path-disclaimer");
  if (disclaimer) disclaimer.hidden = true;
  host.append(pane);
}

function returnMap(ctx) {
  if (!borrowed) return;
  const disclaimer = document.getElementById("path-disclaimer");
  if (disclaimer) disclaimer.hidden = false;
  borrowed.parent.insertBefore(borrowed.pane, borrowed.before);
  borrowed = null;
  if (ctx.state.map) ctx.state.map.invalidateSize();
}

function placeRow(place) {
  const row = document.createElement("div");
  row.className = "fp-dialog-field";
  const dot = document.createElement("span");
  dot.className = "fp-color-swatch";
  dot.style.background = place.color || "#3b82f6";
  const name = document.createElement("span");
  name.textContent = place.name;
  row.append(dot, name);
  return row;
}

export default {
  id: "places",
  canSkip: true,
  render(container, ctx) {
    container.textContent = "";
    const heading = document.createElement("h2");
    heading.textContent = t("setup.places.title");

    const list = document.createElement("div");
    list.id = "fp-setup-places-list";

    const add = document.createElement("button");
    add.type = "button";
    add.className = "btn";
    add.textContent = t("setup.places.add");
    add.addEventListener("click", () => activateCrosshairMode());

    const mapHost = document.createElement("div");
    mapHost.id = "fp-setup-map-host";

    els = { list };
    container.append(heading, list, add, mapHost);
    borrowMap(mapHost);
    if (ctx.state.map) ctx.state.map.invalidateSize();
  },
  async onEnter(ctx) {
    const places = await ctx.api("/api/places");
    els.list.textContent = "";
    places.forEach((place) => els.list.append(placeRow(place)));
  },
  onLeave(ctx) {
    returnMap(ctx);
  },
};
