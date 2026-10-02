/*
 * Onboarding step 2: "Connect your accounts" (Google, Apple, or both).
 *
 * Purpose    : Mount the shared sign-in component (signin/panel.js), the same
 *              cards Settings > Sign-in shows, side by side under a step title,
 *              a one-line lead and a summary of who is connected. In the desktop
 *              app each card's Connect opens Find+'s own sign-in (the Google
 *              window, the Apple sheet) and the card itself says Success.
 * Inputs     : ctx.api / ctx.postJson / ctx.state / ctx.setNextEnabled, handed
 *              down by the Wizard.
 * Outputs    : DOM inside the step container; the sign-in jobs the auth routes
 *              own (specs/in-app-login.md §7, specs/onboarding.md § 4 row 2).
 * Constraints: Next is held until at least one provider is connected (spec §7);
 *              Skip, the Wizard's own button, always moves on, so the wizard
 *              never traps someone who means to sign in later. A hint says so
 *              while Next is held. Both providers can be connected in any
 *              order. Each card carries its provider's honesty sentence from
 *              /api/config (PROMPT.md §2 invariant 4). Leaving the step stops
 *              both polls; a sign-in still running finishes server-side and
 *              shows up in Settings. UAT6-N23: the summary stays blank until
 *              someone is connected; each card already says "Not connected".
 */
"use strict";

import { t } from "../i18n.js";
import { mountSignInPanel } from "../signin/panel.js";

/** The live step's panel, summary line and Next hint, replaced on every render. */
let panel = null;
let summary = null;
let hint = null;

/** "Connected: a@x, b@y." once at least one provider is; blank otherwise. */
function renderSummary(providers, ctx) {
  const signedIn = providers.filter((p) => p.signed_in);
  const locked = providers.some((p) => p.signed_in && (p.needs || []).includes("shared_key"));
  const who = signedIn.length
    ? t("setup.signin.signed_in_as", { accounts: signedIn.map((p) => p.account || p.id).join(", ") })
    : "";
  // A connected Google account whose locations are still locked is not done:
  // say so, because Devices will list trackers that cannot show a position.
  summary.textContent = locked ? `${who} ${t("setup.signin.locked")}` : who;
  hint.hidden = signedIn.length > 0;
  if (ctx.setNextEnabled) ctx.setNextEnabled(signedIn.length > 0);
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
    host.className = "fp-setup-signin-host";
    hint = document.createElement("p");
    hint.id = "fp-setup-signin-next-hint";
    hint.className = "fp-wizard-footnote";
    hint.textContent = t("setup.signin.nextHint");
    container.append(heading, lead, summary, host, hint);
    if (ctx.setNextEnabled) ctx.setNextEnabled(false);

    panel = mountSignInPanel(host, {
      prefix: "fp-setup",
      level: 3,
      withNotices: true,
      api: ctx.api,
      postJson: ctx.postJson,
      notices: () => ctx.state.config && ctx.state.config.notices,
      onStatus: (providers) => renderSummary(providers, ctx),
    });
  },
  async onEnter() {
    await panel.refresh();
  },
  onLeave() {
    if (panel) panel.stop();
  },
};
