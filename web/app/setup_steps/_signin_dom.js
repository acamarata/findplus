/*
 * Shared pieces of the wizard's sign-in step.
 *
 * Purpose    : The row/button builders and the job poller that the Google
 *              branch (signin.js) and the Apple branch (signin_apple.js) both
 *              need, kept here so neither file imports the other.
 * Inputs     : Catalog keys; a ctx with api(); a job route and job id.
 * Outputs    : DOM nodes; a Poller with start()/stop(); a ChromeGate with
 *              show()/static missing().
 * Constraints: No step state of its own. One poll at a time per Poller, and
 *              the 5-minute cap matches the vendor's own WebDriverWait budget.
 *              ChromeGate reads the live /api/config notice rather than a
 *              thrown message's text (T0 addendum B5, split out of signin.js
 *              at the setup-step 150-line cap).
 */
"use strict";

import { t } from "../i18n.js";

/** 2 s per poll, 150 polls: the vendor's own 5-minute sign-in budget. */
export const POLL_MS = 2000;
export const POLL_CAP = 150;

/** A labelled input row, matching the Settings dialog's own `.setting-row`. */
export function field(labelKey, type) {
  const label = document.createElement("label");
  label.className = "setting-row";
  const span = document.createElement("span");
  span.textContent = t(labelKey);
  const input = document.createElement("input");
  input.type = type;
  label.append(span, input);
  return { label, input };
}

/** A small-print paragraph. Honesty sentences are rendered through this. */
export function footnote(text) {
  const p = document.createElement("p");
  p.className = "fp-wizard-footnote";
  p.textContent = text || "";
  return p;
}

export function button(labelKey, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn";
  btn.textContent = t(labelKey);
  btn.addEventListener("click", onClick);
  return btn;
}

/**
 * The Chrome-missing notice under the Google button and the disable it
 * implies — read from GET /api/auth/status's `needs` field on entry and from
 * a 400/chrome_found:false in flight, never from a thrown message's text
 * (providers/auth_status.py already computes `needs` for exactly this).
 */
export class ChromeGate {
  constructor(googleBtn) {
    this.button = googleBtn;
    this.notice = footnote("");
    this.notice.id = "fp-setup-chrome-notice";
    this.notice.hidden = true;
  }

  show(ctx, on) {
    const notices = (ctx.state.config && ctx.state.config.notices) || {};
    this.notice.textContent = on ? notices.chrome_required || "" : "";
    this.notice.hidden = !on;
    this.button.disabled = on;
  }

  static missing(providers) {
    const google = (providers || []).find((p) => p.id === "google-find-hub");
    return !!(google && (google.needs || []).includes("chrome"));
  }
}

/**
 * One interval at a time, cleared on every terminal state and on the cap.
 *
 * A step that re-renders (Back then Next again) calls stop() first, so a stale
 * poll can never write into a container that is no longer on screen.
 */
export class Poller {
  constructor(statusEl) {
    this.statusEl = statusEl;
    this.timer = null;
  }

  stop() {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  start(ctx, path, jobId, onProgress) {
    this.stop();
    let ticks = 0;
    this.timer = setInterval(async () => {
      if (++ticks > POLL_CAP) {
        this.stop();
        this.statusEl.textContent = t("setup.signin.timed_out");
        return;
      }
      try {
        onProgress(await ctx.api(`${path}?job_id=${encodeURIComponent(jobId)}`));
      } catch (err) {
        this.stop();
        this.statusEl.textContent = err.message;
      }
    }, POLL_MS);
  }
}
