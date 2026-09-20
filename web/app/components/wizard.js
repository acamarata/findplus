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
    this.ctx = { api, postJson, state, showAlert };
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

    this.mount.append(this.skipAll, this.progress, this.stepEl, this.footer);
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

  /** Run an async chrome handler, surfacing a thrown api() error in the banner. */
  guard(fn) {
    Promise.resolve()
      .then(fn)
      .catch((err) => showAlert(err.message, "err"));
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
      Promise.resolve(step.onEnter(this.ctx)).catch((err) => showAlert(err.message, "err"));
    }
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
