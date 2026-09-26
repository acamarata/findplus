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
 *              UAT6 N04: a step's onEnter/onNext/guard failure used to reach
 *              ctx.showAlert(), which writes into #alert inside #app-shell --
 *              hidden for the whole time the wizard is open, so the error was
 *              never seen or announced (applock.js/_device_row.js document the
 *              same #alert trap for their own per-field errors). This chrome
 *              now carries its own role="alert" region for exactly those three
 *              call sites; a step's own inline errors (the Devices list, the
 *              Groups name field) are unaffected and keep using their own
 *              elements. ctx also grows three small hooks a step can use
 *              without reaching into the Wizard instance directly: goToStep
 *              (Done's "go fix it" links, UAT6 N19), completeSetup (a step
 *              that finishes onboarding itself, UAT6 N33) and reportError
 *              (routes a failure from outside guard()/onEnter into this same
 *              region).
 */
"use strict";

import { api, postJson } from "../api.js";
import { state, showAlert } from "../state.js";
import { t } from "../i18n.js";

const LAST_STEP_ROUTE = "/api/settings/onboarding.last_step";
const COMPLETED_ROUTE = "/api/settings/onboarding.completed_at";

export class Wizard {
  constructor({ steps, mount, onStep, onDone, initialStep }) {
    this.steps = steps;
    this.mount = mount;
    this.onStep = onStep || null;
    this.onDone = onDone || (() => {});
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
    };
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

    this.skipAll = document.createElement("button");
    this.skipAll.type = "button";
    this.skipAll.id = "fp-wizard-skip-all";
    this.skipAll.className = "fp-wizard-skip";
    this.skipAll.textContent = t("setup.skip_all");
    this.skipAll.addEventListener("click", () => this.guard(() => this.complete()));

    this.progress = document.createElement("div");
    this.progress.className = "fp-wizard-progress";
    this.progress.setAttribute("aria-live", "polite");
    this.progressText = document.createElement("span");
    this.progressText.className = "fp-wizard-progress-text";
    this.dots = this.steps.map(() => {
      const dot = document.createElement("span");
      dot.className = "fp-wizard-dot";
      return dot;
    });
    this.progress.append(this.progressText, ...this.dots);

    this.stepEl = document.createElement("div");
    this.stepEl.className = "fp-wizard-step";

    // UAT6 N04: the one place a guard()/onEnter failure is actually seen.
    this.errorEl = document.createElement("p");
    this.errorEl.id = "fp-wizard-error";
    this.errorEl.className = "fp-dialog-error";
    this.errorEl.setAttribute("role", "alert");

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

    this.mount.append(this.skipAll, this.progress, this.stepEl, this.errorEl, this.footer);
  }

  /** Show (or clear, with an empty/falsy message) the chrome's own error line. */
  setError(message) {
    this.errorEl.textContent = message || "";
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
    Promise.resolve()
      .then(fn)
      .catch((err) => this.setError(err.message))
      .finally(() => {
        this.busy = false;
        chrome.forEach((btn) => (btn.disabled = false));
        if (focused && !focused.hidden && document.activeElement === document.body) {
          focused.focus();
        }
      });
  }

  /** Paint the active step and reconcile the chrome around it. */
  renderStep() {
    const step = this.steps[this.index];
    const last = this.index === this.steps.length - 1;

    this.progressText.textContent = t("setup.progress", {
      n: this.index + 1,
      total: this.steps.length,
    });
    this.dots.forEach((dot, i) => dot.classList.toggle("filled", i <= this.index));

    this.setError("");
    this.stepEl.textContent = "";
    step.render(this.stepEl, this.ctx);

    this.backBtn.hidden = this.index === 0;
    this.skipBtn.hidden = !step.canSkip;
    this.skipAll.hidden = last;
    this.nextBtn.textContent = last ? t("setup.done.button") : t("setup.next");

    if (this.onStep) this.onStep(step, this.index);
    // Fired after the chrome settles so a slow re-fetch cannot leave the
    // footer describing the previous step.
    if (step.onEnter) {
      Promise.resolve(step.onEnter(this.ctx)).catch((err) => this.setError(err.message));
    }
  }

  /**
   * Jump straight to a step by id, outside the Back/Skip/Next machinery.
   *
   * Used by a step that offers "go fix this" rather than a linear Next (the
   * Done step's recovery link when nothing ended up signed in or tracked,
   * UAT6 N19). Deliberately not routed through guard(): that lock exists to
   * stop a double-click from repeating the SAME transition, which does not
   * apply to a link a user reads once and follows once.
   */
  goToStep(id) {
    const index = this.steps.findIndex((s) => s.id === id);
    if (index < 0 || index === this.index) return;
    this.advance(index).catch((err) => this.setError(err.message));
  }

  /**
   * Move to `toIndex`, recording the resume point BEFORE the new step renders.
   *
   * The order matters: a reload that lands between the write and the paint
   * must come back to the step the user was about to see, not the one they
   * just left.
   */
  async advance(toIndex) {
    const target = this.steps[toIndex];
    if (!target) return;
    this.leaveCurrent();
    await postJson(LAST_STEP_ROUTE, { value: target.id });
    this.index = toIndex;
    this.renderStep();
  }

  /**
   * Let the step being left put back anything it borrowed.
   *
   * The Places step moves the shared map into its own container; without this
   * hook it would have nowhere to hand it back from.
   */
  leaveCurrent() {
    const step = this.steps[this.index];
    if (step && step.onLeave) step.onLeave(this.ctx);
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
    await postJson(COMPLETED_ROUTE, { value: new Date().toISOString() });
    this.onDone();
  }
}
