/*
 * Onboarding step 5 — Places (optional).
 *
 * Purpose    : List the geofences that exist and offer the same "Add place"
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
 *              describe (visual gate W4 F3). UAT N6: the dialog's own
 *              onSaved callback (wired by the dashboard's places.js) reloads
 *              the DASHBOARD's list, which is hidden behind the wizard -- this
 *              step reloads its own list off the dialog's "close" event
 *              instead, the same pattern _device_row.js's Edit button uses.
 *              The map opens fitted to the tracked devices (or saved places)
 *              via map.js's own setDefaultView(), instead of world zoom.
 */
"use strict";

import { t } from "../i18n.js";
import { showAddDialog } from "../places_dialog.js";
import { setDefaultView } from "../map.js";

/** Where `.map-pane` came from, so onLeave can put it back exactly there. */
let borrowed = null;
let els = null;

/**
 * Move the shared map into the step, remembering where it was.
 *
 * #app-shell is hidden while the wizard is open, so the map has to come to
 * the wizard for "Add place" to have a centre to open the dialog at.
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

/** Re-fetch and repaint the step's own list (onEnter, and after Add saves). */
async function reloadList(ctx) {
  const places = await ctx.api("/api/places");
  els.list.textContent = "";
  places.forEach((place) => els.list.append(placeRow(place)));
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
    // U4/U10: opens the dialog at the borrowed map's own current centre,
    // same as the dashboard's "Add place" — no map click required here
    // either. N6: the dialog's own onSaved callback reloads the dashboard's
    // (hidden) list, not this one, so reload off the dialog's own close —
    // fired on Save and on Cancel alike, matching _device_row.js's edit flow.
    add.addEventListener("click", () => {
      showAddDialog(ctx.state.map.getCenter());
      const dlg = document.getElementById("fp-place-dialog");
      if (dlg) {
        dlg.addEventListener("close", () => reloadList(ctx).catch(() => {}), { once: true });
      }
    });

    const mapHost = document.createElement("div");
    mapHost.id = "fp-setup-map-host";

    els = { list };
    container.append(heading, list, add, mapHost);
    borrowMap(mapHost);
    if (ctx.state.map) ctx.state.map.invalidateSize();
  },
  async onEnter(ctx) {
    await reloadList(ctx);
    // N6: a fresh borrowed map defaulted to world zoom with no tracker
    // markers to give it a reason to zoom in. Fit it the same way the
    // dashboard does: tracked devices' latest fixes, else saved places.
    await setDefaultView().catch(() => {});
  },
  onLeave(ctx) {
    returnMap(ctx);
  },
};
