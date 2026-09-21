/*
 * Onboarding wizard: mount point and step registry.
 *
 * Purpose    : Name Find+'s eight onboarding steps, in order, and hand them to
 *              the generic Wizard (components/wizard.js) mounted in #setup-view.
 * Inputs     : The resume point, `onboarding.last_step`, passed by the caller.
 * Outputs    : mountSetup() -> the live Wizard instance; closeSetup()/purge()
 *              tear it back down.
 * Constraints: Mount and registry only (ruling F16). No step markup, no step
 *              logic and no API call lives in this file — each step is its own
 *              module under setup_steps/.
 */
"use strict";

import { Wizard } from "./components/wizard.js";
import { state } from "./state.js";
import welcomeStep from "./setup_steps/welcome.js";
import signinStep from "./setup_steps/signin.js";
import devicesStep from "./setup_steps/devices.js";
import groupsStep from "./setup_steps/groups.js";
import placesStep from "./setup_steps/places.js";
import notificationsStep from "./setup_steps/notifications.js";
import applockStep from "./setup_steps/applock.js";
import doneStep from "./setup_steps/done.js";

/** The eight steps in specs/onboarding.md § 4's order. */
export const SETUP_STEPS = [
  welcomeStep,
  signinStep,
  devicesStep,
  groupsStep,
  placesStep,
  notificationsStep,
  applockStep,
  doneStep,
];

/** The wizard currently on screen, so it can be torn down from outside. */
let active = null;

/**
 * Destroy the wizard and give the dashboard back.
 *
 * Not "hide": every field the wizard rendered is removed from the document.
 * An Apple ID, an unsent password, a Telegram bot token, two PIN boxes and
 * every discovered tracker's name live in here, and a closed-but-present view
 * keeps all of them readable in DevTools (PROMPT.md § 2: a purge destroys).
 * Idempotent, so the route, onDone and the lock can all call it.
 */
export function closeSetup() {
  const view = document.getElementById("setup-view");
  // Hand the borrowed map back BEFORE the container is emptied: the Places
  // step moves the one Leaflet pane into itself, and clearing the view with
  // the pane still inside would delete the dashboard's map for good.
  if (active) active.leaveCurrent();
  active = null;
  view.textContent = "";
  view.hidden = true;
  document.getElementById("app-shell").classList.remove("hidden");
}

/** What lock.js calls: the wizard's share of the post-lock purge. */
export function purge() {
  closeSetup();
}

export async function mountSetup(initialStep) {
  // A second mount over a live one (an unlock that lands back on #/setup) must
  // let the old wizard give the map pane back first: the Wizard constructor
  // empties its mount, and the pane would go with it.
  if (active) active.leaveCurrent();
  document.getElementById("setup-view").hidden = false;
  active = new Wizard({
    steps: SETUP_STEPS,
    mount: document.getElementById("setup-view"),
    onDone: () => {
      window.location.hash = "";
      closeSetup();
      // First launch: the dashboard has never booted, so boot it. A re-entry
      // from Settings already has a live dashboard and must not boot a second
      // one, which would stack a duplicate refresh timer.
      if (!state.dashboardBooted) {
        import("./main.js").then((m) => m.bootDashboard(null));
      }
    },
    initialStep,
  });
  return active;
}
