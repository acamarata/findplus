/*
 * Onboarding step 8 — Done.
 *
 * Purpose    : Say what the session set up, and nothing else
 *              (specs/onboarding.md § 4 row 8).
 * Inputs     : GET /api/devices' own tracked_count (the same figure the
 *              dashboard widget uses) and GET /api/auth/status.
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
 *              CI flake fix (2026-09-25): render() paints the heading before
 *              onEnter's fetch settles (wizard.js fires onEnter without
 *              awaiting it, on purpose, so a slow re-fetch cannot hold up the
 *              chrome). The summary paragraph carries data-ready="false"
 *              until the count actually lands, so nothing -- a screen reader
 *              or a test -- reads "You're set up" as a signal that the count
 *              underneath it is final.
 *              UAT6-N19: "You're set up · 0 devices tracked" with nobody
 *              signed in and nothing tracked read as a success, when it is
 *              exactly the state that needs fixing. That combination (both
 *              empty, not just a deliberate 0) now swaps the heading and
 *              summary for a plain "nothing connected yet" pair and offers a
 *              button straight back to Sign-in, instead of celebrating.
 */
"use strict";

import { plural, t } from "../i18n.js";

/** The live step's elements, replaced on every render. */
let els = null;

function renderComplete(trackedCount) {
  els.heading.textContent = t("setup.done.title");
  els.summary.textContent = plural("setup.done.summary", trackedCount, { n: trackedCount });
  els.signinBtn.hidden = true;
}

function renderIncomplete() {
  els.heading.textContent = t("setup.done.incomplete_title");
  els.summary.textContent = t("setup.done.incomplete_summary");
  els.signinBtn.hidden = false;
}

export default {
  id: "done",
  canSkip: false,
  render(container, ctx) {
    container.textContent = "";
    const heading = document.createElement("h2");
    heading.textContent = t("setup.done.title");
    const summary = document.createElement("p");
    summary.setAttribute("aria-live", "polite");
    summary.dataset.ready = "false";
    const signinBtn = document.createElement("button");
    signinBtn.type = "button";
    signinBtn.id = "fp-setup-done-signin";
    signinBtn.className = "btn btn-secondary";
    signinBtn.textContent = t("setup.done.go_to_signin");
    signinBtn.hidden = true;
    signinBtn.addEventListener("click", () => ctx.goToStep("signin"));
    els = { heading, summary, signinBtn };
    container.append(heading, summary, signinBtn);
  },
  async onEnter(ctx) {
    const [{ tracked_count: trackedCount }, authStatus] = await Promise.all([
      ctx.api("/api/devices"),
      ctx.api("/api/auth/status"),
    ]);
    const signedIn = (authStatus.providers || []).some((p) => p.signed_in);
    if (signedIn || trackedCount) renderComplete(trackedCount);
    else renderIncomplete();
    // Set last, after either branch has painted its own final text: this is
    // what tells a reader (or a test) the async fetch has actually landed.
    els.summary.dataset.ready = "true";
  },
};
