/*
 * Onboarding step 1 — Welcome.
 *
 * Purpose    : Say what Find+ is and that it runs locally, with the
 *              "not affiliated" sentence as a footnote.
 * Inputs     : ctx.state.config.notices, already loaded by main.js's boot.
 * Outputs    : DOM inside the step container.
 * Constraints: Display only. No API call, no forward button of its own — the
 *              Wizard's Next footer button is the only way on
 *              (specs/onboarding.md § 4 row 1).
 */
"use strict";

import { t } from "../i18n.js";

export default {
  id: "welcome",
  canSkip: false,
  render(container, ctx) {
    container.textContent = "";
    const heading = document.createElement("h2");
    heading.textContent = t("setup.welcome.title");
    const body = document.createElement("p");
    body.textContent = t("setup.welcome.body");
    const note = document.createElement("p");
    note.className = "fp-wizard-footnote";
    // Sourced from /api/config.notices, never re-keyed into the catalog, so
    // there is exactly one place this sentence can drift from honesty.py.
    note.textContent = (ctx.state.config && ctx.state.config.notices.not_affiliated) || "";
    container.append(heading, body, note);
  },
};
