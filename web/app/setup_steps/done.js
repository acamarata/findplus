/*
 * Onboarding step 8 — Done.
 *
 * Purpose    : Say what the session set up, and nothing else
 *              (specs/onboarding.md § 4 row 8).
 * Inputs     : ctx.state.devices, whatever the Devices step last loaded.
 * Outputs    : DOM inside the step container.
 * Constraints: Display only, and deliberately without an onNext: the Wizard's
 *              own Done button is the single writer of
 *              `onboarding.completed_at` from inside the wizard. No fetch — a
 *              skipped Devices step correctly leaves the count at zero.
 */
"use strict";

import { t } from "../i18n.js";

export default {
  id: "done",
  canSkip: false,
  render(container, ctx) {
    container.textContent = "";
    const trackedCount = (ctx.state.devices || []).filter((d) => d.is_tracked).length;
    const heading = document.createElement("h2");
    heading.textContent = t("setup.done.title");
    const summary = document.createElement("p");
    summary.textContent = t("setup.done.summary", { n: trackedCount });
    container.append(heading, summary);
  },
};
