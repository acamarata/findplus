/*
 * Onboarding step 8 — Done.
 *
 * Purpose    : Say what the session set up, and nothing else
 *              (specs/onboarding.md § 4 row 8).
 * Inputs     : GET /api/devices' own tracked_count, the same figure the
 *              dashboard widget uses.
 * Outputs    : DOM inside the step container.
 * Constraints: Display only, and deliberately without an onNext: the Wizard's
 *              own Done button is the single writer of
 *              `onboarding.completed_at` from inside the wizard.
 *              UAT4 N29: this used to filter ctx.state.devices, which is only
 *              ever populated by the Devices step actually running this
 *              session (onEnter/onNext there). A reload that resumed setup
 *              past that step, or a Devices step the user skipped, left it
 *              `[]` and showed "0 devices tracked" over six real tracked
 *              devices. The server's own count is never stale this way.
 */
"use strict";

import { plural, t } from "../i18n.js";

/** The live step's elements, replaced on every render. */
let els = null;

export default {
  id: "done",
  canSkip: false,
  render(container, ctx) {
    container.textContent = "";
    const heading = document.createElement("h2");
    heading.textContent = t("setup.done.title");
    const summary = document.createElement("p");
    els = { summary };
    container.append(heading, summary);
  },
  async onEnter(ctx) {
    const { tracked_count: trackedCount } = await ctx.api("/api/devices");
    els.summary.textContent = plural("setup.done.summary", trackedCount, { n: trackedCount });
  },
};
