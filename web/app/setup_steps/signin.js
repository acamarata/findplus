/*
 * Onboarding step 2 — Sign in.
 *
 * Purpose    : Start a Google Find Hub or Apple Find My sign-in from inside the
 *              wizard, each under its own honesty sentence.
 * Inputs     : ctx.api / ctx.postJson / ctx.state, handed down by the Wizard.
 * Outputs    : DOM inside the step container; the sign-in jobs the auth routes
 *              own (specs/auth-ui.md § 3, specs/onboarding.md § 4 row 2).
 * Constraints: Skipping is the Wizard's own Skip button — this step renders no
 *              skip link of its own. Next always advances: the wizard must
 *              never trap someone who means to sign in later. Each provider
 *              gets the same `.fp-auth-provider` sub-heading the Settings
 *              dialog's sign-in panel shows (R-P2-28 point 4) — the two
 *              honesty footnotes read as unattributed sentences without one
 *              (matches settings.html's own comment: the served markup keeps
 *              them empty, catalog values fill them at boot, so "Google"/
 *              "Find Hub" never appear as a literal in test_honesty_notices.py's
 *              static-file scan). The Chrome-missing notice (T0 addendum B5,
 *              e13/blind-gp-adjudicated.md) is read from GET /api/auth/status's
 *              `needs` field on entry, and never from a raw thrown message: the
 *              route's only 400 is ChromeNotFoundError, whose text is already
 *              honesty.CHROME_REQUIRED (routes_auth.py), but this reads it
 *              through the live /api/config notice rather than trusting that
 *              coincidence to hold.
 */
"use strict";

import { t } from "../i18n.js";
import { Poller, ChromeGate, button, footnote } from "./_signin_dom.js";
import { buildAppleBranch } from "./signin_apple.js";

/** Google progress state -> the catalog key that describes it. */
const GOOGLE_STATE_KEYS = {
  launching: "setup.signin.starting",
  waiting_for_user: "setup.signin.waiting",
  capturing: "setup.signin.finishing",
};

/** The live step's elements, replaced on every render. */
let els = null;

function watchGoogle(ctx, jobId) {
  els.poller.start(ctx, "/api/auth/google/progress", jobId, (progress) => {
    // Recomputed on every poll (routes_auth.py), so Chrome going missing
    // mid-job is reported the same way a missing Chrome at start is.
    if (progress.chrome_found === false) {
      els.chrome.show(ctx, true);
      els.poller.stop();
      return;
    }
    const key = GOOGLE_STATE_KEYS[progress.state];
    // A finished or failed job carries the server's own explanation, which
    // is more use than any generic line this file could put in its place.
    els.status.textContent = key ? t(key) : progress.message;
    if (progress.state === "done" || progress.state === "failed") els.poller.stop();
  });
}

/**
 * The job id of a sign-in already running, if that is what went wrong.
 *
 * The route answers 409 with the running job's id rather than starting a
 * second Chrome. Rejoining it is the only way a reloaded wizard can follow a
 * sign-in it started before the reload (CR-C-E10 F1).
 */
function runningJobId(err) {
  return err.status === 409 && err.body ? err.body.job_id : null;
}

/** Same class and catalog keys the Settings dialog's sign-in panel uses. */
function providerHeading(key) {
  const h = document.createElement("h4");
  h.className = "fp-auth-provider";
  h.textContent = t(`auth.${key}.heading`);
  return h;
}

function startGoogle(ctx) {
  els.status.textContent = t("setup.signin.starting");
  ctx.postJson("/api/auth/google/start")
    .then(({ job_id: jobId }) => watchGoogle(ctx, jobId))
    .catch((err) => {
      const existing = runningJobId(err);
      if (existing) {
        // Cleared rather than left reading "Starting Chrome...": the first
        // poll response overwrites it anyway, but a rejoin can land on a job
        // already past that state (loop2 B1).
        els.status.textContent = "";
        watchGoogle(ctx, existing);
        return;
      }
      // The route's only 400 is ChromeNotFoundError (routes_auth.py): mapped
      // through the live notice, never the raw thrown message (B5). The
      // status line is cleared here too -- otherwise it keeps reading
      // "Starting Chrome..." forever beside the now-visible Chrome-missing
      // notice, a contradictory pair of things to tell someone at once
      // (loop2 B1).
      if (err.status === 400) {
        els.status.textContent = "";
        els.chrome.show(ctx, true);
        return;
      }
      els.status.textContent = err.message;
    });
}

export default {
  id: "signin",
  canSkip: true,
  render(container, ctx) {
    if (els) {
      els.poller.stop();
      els.apple.stop();
    }
    container.textContent = "";
    const notices = (ctx.state.config && ctx.state.config.notices) || {};

    const heading = document.createElement("h2");
    heading.textContent = t("setup.signin.title");
    const status = document.createElement("p");
    status.id = "fp-setup-signin-status";
    const apple = buildAppleBranch(ctx, status);
    const googleBtn = button("setup.signin.google", () => startGoogle(ctx));
    const chrome = new ChromeGate(googleBtn);
    els = { status, poller: new Poller(status), apple, chrome, googleBtn };

    container.append(
      heading,
      status,
      providerHeading("google"),
      googleBtn,
      chrome.notice,
      footnote(notices.find_hub),
      providerHeading("apple"),
      button("setup.signin.apple", () => apple.open()),
      footnote(notices.apple),
      apple.form,
      apple.codeRow
    );
  },
  async onEnter(ctx) {
    const { providers } = await ctx.api("/api/auth/status");
    const signedIn = (providers || []).filter((p) => p.signed_in);
    els.status.textContent = signedIn.length
      ? t("setup.signin.signed_in_as", {
          accounts: signedIn.map((p) => p.account || p.id).join(", "),
        })
      : t("setup.signin.not_signed_in");
    els.chrome.show(ctx, ChromeGate.missing(providers));
    // UAT U33: the button still offered a fresh "Sign in with Google" after
    // the status line above it already said "Signed in as...". Its own label
    // now carries the state too, and stays clickable so switching accounts
    // is still one click, not a dead end.
    const google = (providers || []).find((p) => p.id === "google-find-hub");
    els.googleBtn.textContent = t(
      google && google.signed_in ? "setup.signin.google_signed_in" : "setup.signin.google"
    );
  },
};
