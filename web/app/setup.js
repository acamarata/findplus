/*
 * Onboarding wizard: mount point and step registry.
 *
 * Purpose    : Name Find+'s eight onboarding steps, in order, and hand them to
 *              the generic Wizard (components/wizard.js) mounted in #setup-view.
 * Inputs     : The resume point, `onboarding.last_step`, passed by the caller.
 * Outputs    : mountSetup() -> the live Wizard instance.
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

export async function mountSetup(initialStep) {
  document.getElementById("setup-view").hidden = false;
  return new Wizard({
    steps: SETUP_STEPS,
    mount: document.getElementById("setup-view"),
    onDone: () => {
      window.location.hash = "";
      document.getElementById("setup-view").hidden = true;
      document.getElementById("app-shell").classList.remove("hidden");
      // First launch: the dashboard has never booted, so boot it. A re-entry
      // from Settings already has a live dashboard and must not boot a second
      // one, which would stack a duplicate refresh timer.
      if (!state.dashboardBooted) {
        import("./main.js").then((m) => m.bootDashboard(null));
      }
    },
    initialStep,
  });
}
