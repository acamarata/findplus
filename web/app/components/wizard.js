/*
 * Generic wizard stepper.
 *
 * Purpose    : Drive any ordered list of steps: a progress row, the active
 *              step's DOM, a Back/Skip/Next-or-Done footer, and the two
 *              settings-table writes that make a reload resume where the user
 *              left off (specs/onboarding.md § 3).
 * Inputs     : { steps, mount, onStep, onDone, initialStep }. A step is
 *              { id, render(container, ctx), canSkip, onEnter?, onNext?,
 *              onLeave? }.
 * Outputs    : DOM under `mount`; POST /api/settings/onboarding.last_step on
 *              every transition and .../onboarding.completed_at on Done or the
 *              global Skip; onDone() when the wizard closes.
 * Constraints: Content-free. It never names a step id, a title or a count
 *              beyond steps.length — setup.js is the only file that knows
 *              Find+ has eight steps. Every label comes from the catalog.
 *              This is also the one module that imports api.js/state.js on a
 *              step's behalf: a step file only reads them off its ctx argument.
 *              The chrome owns a role="alert" region for step/guard failures
 *              (#alert lives in the hidden #app-shell, UAT6 N04), and ctx
 *              carries goToStep, completeSetup, reportError, setNextEnabled
 *              and rerun for steps.
 *              Moving to a step focuses its heading; typed values survive
 *              Back/Skip through wizard_drafts.js; a re-run never re-stamps.
 */
"use strict";

import { api, postJson } from "../api.js";
import { state, showAlert } from "../state.js";
import { t } from "../i18n.js";
import { saveDraft, restoreDraft } from "./wizard_drafts.js";
import { closeButton } from "./wizard_close.js";

const LAST_STEP_ROUTE = "/api/settings/onboarding.last_step";
const COMPLETED_ROUTE = "/api/settings/onboarding.completed_at";

export class Wizard {
  constructor({ steps, mount, onStep, onDone, initialStep, rerun }) {
    this.steps = steps;
    this.mount = mount;
    this.onStep = onStep || null;
    this.onDone = onDone || (() => {});
    /** Re-running setup from Settings: finishing must not re-stamp the date. */
    this.rerun = !!rerun;
    /** What was typed per step, so Back and Skip never lose it. */
    this.drafts = new Map();
    this.onNet = () => this.showNet();
    // Built once and handed unchanged to every step call, so each step sees
    // the same `state` reference for the whole wizard session.
    this.ctx = {
      api,
      postJson,
      state,
      showAlert,
      goToStep: (id) => this.goToStep(id),
      completeSetup: () => this.complete(),
      reportError: (message) => this.setError(message),
      setNextEnabled: (on) => this.setNextEnabled(on),
      rerun: this.rerun,
    };
    this.nextHeld = false; // a step may hold Next (sign-in: until one account)
    /** True while a Back/Skip/Next/Skip-setup transition is still in flight. */
    this.busy = false;
    const found = initialStep ? steps.findIndex((s) => s.id === initialStep) : 0;
    this.index = found > 0 ? found : 0;
    this.buildChrome();
    this.renderStep();
  }

  /** The skip link, progress row, step container and footer, created once. */
  buildChrome() {
    this.mount.textContent = "";

    // U38: an icon button (X); the words ride on its aria-label and tooltip.
    this.skipAll = closeButton(t(this.rerun ? "setup.close_rerun" : "setup.skip_all"), () =>
      this.guard(() => this.complete())
    );

    this.buildProgress();

    this.stepEl = document.createElement("div");
    this.stepEl.className = "fp-wizard-step";

    // Offline notice: on while the browser reports no connection.
    this.netEl = document.createElement("div");
    this.netEl.id = "fp-wizard-offline";
    this.netEl.className = "fp-wizard-offline";
    this.netEl.setAttribute("role", "status");
    window.addEventListener("offline", this.onNet);
    window.addEventListener("online", this.onNet);
    this.showNet();

    // UAT6 N04: the one place a guard()/onEnter failure is actually seen.
    this.errorEl = document.createElement("p");
    this.errorEl.id = "fp-wizard-error";
    this.errorEl.className = "fp-dialog-error";
    this.errorEl.setAttribute("role", "alert");

    this.buildFooter();

    this.mount.append(
      this.skipAll, this.progress, this.netEl, this.stepEl, this.errorEl, this.footer
    );
  }

  /** The named progress group: "2 of 8" text plus one decorative segment each. */
  buildProgress() {
    this.progress = document.createElement("div");
    this.progress.className = "fp-wizard-progress";
    // A named group, not a live region: moving focus to the step heading is
    // what announces a new step, so this never speaks a second time.
    this.progress.setAttribute("role", "group");
    this.progressText = document.createElement("span");
    this.progressText.className = "fp-wizard-progress-text";
    this.progressText.setAttribute("aria-hidden", "true");
    this.dots = this.steps.map(() => {
      const dot = document.createElement("span");
      dot.className = "fp-wizard-dot";
      dot.setAttribute("aria-hidden", "true");
      return dot;
    });
    this.progress.append(this.progressText, ...this.dots);
  }

  /** Back / Skip / Next, wired to the guarded transitions. */
  buildFooter() {
    this.footer = document.createElement("div");
    this.footer.className = "fp-wizard-footer";
    this.backBtn = this.footerButton("fp-wizard-back", t("setup.back"), "btn btn-secondary", () =>
      this.guard(() => this.advance(this.index - 1))
    );
    this.skipBtn = this.footerButton("fp-wizard-skip", t("setup.skip"), "btn btn-secondary", () =>
      this.guard(() => this.advance(this.index + 1))
    );
    this.nextBtn = this.footerButton("fp-wizard-next", t("setup.next"), "btn", () =>
      this.guard(() => this.next())
    );
    this.footer.append(this.backBtn, this.skipBtn, this.nextBtn);
  }

  /** Offline line on or off, from the browser's own connection state. */
  showNet() {
    this.netEl.textContent = navigator.onLine === false ? t("setup.offline") : "";
  }

  /** Tear down: forget every draft and stop listening for connection changes. */
  destroy() {
    this.drafts.clear();
    window.removeEventListener("offline", this.onNet);
    window.removeEventListener("online", this.onNet);
  }

  /** Show (or clear, with an empty/falsy message) the chrome's own error line. */
  setError(message) {
    this.errorEl.textContent = message || "";
  }

  /** Hold or release Next for the current step; Skip is never held. */
  setNextEnabled(on) {
    this.nextHeld = !on;
    if (!this.busy) this.nextBtn.disabled = this.nextHeld;
  }

  footerButton(id, label, className, handler) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = id;
    btn.className = className;
    btn.textContent = label;
    btn.addEventListener("click", handler);
    return btn;
  }

  /**
   * Run one chrome handler at a time, surfacing a thrown api() error.
   *
   * The buttons are disabled for the duration: a transition is two awaited
   * requests long, and a second click inside that window ran the step's
   * onNext twice (two POST /api/devices/track) or stamped completed_at twice.
   */
  guard(fn) {
    if (this.busy) return;
    this.busy = true;
    this.setError("");
    const chrome = [this.backBtn, this.skipBtn, this.nextBtn, this.skipAll];
    // Disabling the button the keyboard is on drops focus to <body>, which
    // would restart every Tab cycle at the top of the page; it goes back
    // afterwards so the wizard can be walked end to end on the keyboard.
    const focused = chrome.includes(document.activeElement) ? document.activeElement : null;
    chrome.forEach((btn) => (btn.disabled = true));
    this.nextBtn.setAttribute("aria-busy", "true");
    Promise.resolve()
      .then(fn)
      .catch((err) => this.setError(err.message))
      .finally(() => {
        this.busy = false;
        chrome.forEach((btn) => (btn.disabled = false));
        this.nextBtn.disabled = this.nextHeld;
        this.nextBtn.removeAttribute("aria-busy");
        if (focused && !focused.hidden && document.activeElement === document.body) {
          focused.focus();
        }
      });
  }

  /** Paint the active step and reconcile the chrome around it. */
  renderStep() {
    const step = this.steps[this.index];
    const last = this.index === this.steps.length - 1;

    const counts = { n: this.index + 1, total: this.steps.length };
    this.progressText.textContent = t("setup.progress", counts);
    this.progress.setAttribute(
      "aria-label",
      t("setup.progress_named", { ...counts, name: t(`setup.step_names.${step.id}`) })
    );
    this.dots.forEach((dot, i) => dot.classList.toggle("filled", i <= this.index));

    this.setError("");
    this.setNextEnabled(true);
    this.stepEl.textContent = "";
    step.render(this.stepEl, this.ctx);
    restoreDraft(this.drafts, step.id, this.stepEl);
    this.focusHeading();

    this.backBtn.hidden = this.index === 0;
    this.skipBtn.hidden = !step.canSkip;
    this.skipAll.hidden = last;
    this.nextBtn.textContent = last
      ? t("setup.done.button")
      : t(step.nextLabel || "setup.next");

    if (this.onStep) this.onStep(step, this.index);
    // Fired after the chrome settles so a slow re-fetch cannot leave the
    // footer describing the previous step.
    if (step.onEnter) {
      Promise.resolve(step.onEnter(this.ctx))
        // A step that builds its fields in onEnter (Notifications) gets its
        // draft back once they exist.
        .then(() => restoreDraft(this.drafts, step.id, this.stepEl))
        .catch((err) => this.setError(err.message));
    }
  }

  /** Put keyboard and screen-reader focus on the new step's heading. */
  focusHeading() {
    const heading = this.stepEl.querySelector("h2");
    if (!heading) return;
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }

  /** Jump to a step by id (Done's "go fix it" links, UAT6 N19). Not guarded:
   * that lock stops a double-click repeating one transition, not a link. */
  goToStep(id) {
    const index = this.steps.findIndex((s) => s.id === id);
    if (index < 0 || index === this.index) return;
    this.advance(index).catch((err) => this.setError(err.message));
  }

  /** Move to `toIndex`, recording the resume point BEFORE the new step renders. */
  async advance(toIndex) {
    const target = this.steps[toIndex];
    if (!target) return;
    this.leaveCurrent();
    await postJson(LAST_STEP_ROUTE, { value: target.id });
    this.index = toIndex;
    this.renderStep();
  }

  /** Let the step being left put back what it borrowed (Places borrows the map). */
  leaveCurrent() {
    const step = this.steps[this.index];
    if (!step) return;
    saveDraft(this.drafts, step.id, this.stepEl);
    if (step.onLeave) step.onLeave(this.ctx);
  }

  /** Next: let the step veto, then advance or finish. */
  async next() {
    const step = this.steps[this.index];
    if (step.onNext && (await step.onNext(this.ctx)) === false) return;
    if (this.index === this.steps.length - 1) {
      await this.complete();
      return;
    }
    await this.advance(this.index + 1);
  }

  /** Stamp onboarding complete and hand control back to the caller. */
  async complete() {
    this.leaveCurrent();
    // A re-run from Settings keeps the original "set up on" date.
    if (!this.rerun) await postJson(COMPLETED_ROUTE, { value: new Date().toISOString() });
    this.onDone();
  }
}
