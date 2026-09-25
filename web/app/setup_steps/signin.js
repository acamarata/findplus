/*
 * Onboarding step 2: connect Google Find Hub and/or Apple Find My.
 *
 * Purpose    : Mount the shared sign-in component (signin/panel.js), the same
 *              cards Settings > Sign-in shows, under a step title, a one-line
 *              lead and a summary of who is signed in.
 * Inputs     : ctx.api / ctx.postJson / ctx.state, handed down by the Wizard.
 * Outputs    : DOM inside the step container; the sign-in jobs the auth routes
 *              own (specs/auth-ui.md § 3, specs/onboarding.md § 4 row 2).
 * Constraints: Skipping is the Wizard's own Skip button; this step renders no
 *              skip link of its own, and Next always advances, so the wizard
 *              never traps someone who means to sign in later. Each card
 *              carries its provider's honesty sentence from /api/config
 *              (PROMPT.md §2 invariant 4). Leaving the step stops both polls;
 *              a sign-in already running in Chrome still finishes server-side
 *              and shows up in Settings.
 */
"use strict";

import { t } from "../i18n.js";
import { mountSignInPanel } from "../signin/panel.js";

/** The live step's panel and summary line, replaced on every render. */
let panel = null;
let summary = null;

/** "Signed in as a@x, b@y." or "Not signed in yet." above the cards. */
function renderSummary(providers) {
  const signedIn = providers.filter((p) => p.signed_in);
  summary.textContent = signedIn.length
    ? t("setup.signin.signed_in_as", { accounts: signedIn.map((p) => p.account || p.id).join(", ") })
    : t("setup.signin.not_signed_in");
}

export default {
  id: "signin",
  canSkip: true,
  render(container, ctx) {
    if (panel) panel.stop();
    container.textContent = "";

    const heading = document.createElement("h2");
    heading.textContent = t("setup.signin.title");
    const lead = document.createElement("p");
    lead.className = "fp-wizard-lead";
    lead.textContent = t("setup.signin.lead");
    summary = document.createElement("p");
    summary.id = "fp-setup-signin-status";
    summary.className = "fp-wizard-summary";
    summary.setAttribute("aria-live", "polite");
    const host = document.createElement("div");
    container.append(heading, lead, summary, host);

    panel = mountSignInPanel(host, {
      prefix: "fp-setup",
      level: 3,
      withNotices: true,
      api: ctx.api,
      postJson: ctx.postJson,
      notices: () => ctx.state.config && ctx.state.config.notices,
      onStatus: renderSummary,
    });
  },
  async onEnter() {
    await panel.refresh();
  },
  onLeave() {
    if (panel) panel.stop();
  },
};
