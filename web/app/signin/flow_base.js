/*
 * The state display both sign-in flows share.
 *
 * Purpose    : One card, one visible state at a time: idle, busy (a spinner
 *              and a line saying what is happening), failed (the reason and a
 *              Retry button) or signed in. The card's data-state attribute
 *              carries it for the stylesheet (signin.css).
 * Inputs     : A card from cards.js and the panel's deps ({ api, postJson,
 *              notices(), onSettled() }).
 * Outputs    : DOM state on that card only.
 * Constraints: textContent only: a failure detail can come from the daemon
 *              and must never run as markup. Retry is wired by the subclass,
 *              because what "again" means differs per provider.
 */
"use strict";

import { JobPoller } from "./job_poller.js";

export class FlowBase {
  constructor(card, deps) {
    this.card = card;
    this.deps = deps;
    this.poller = new JobPoller(deps.api);
    this.signedIn = false;
  }

  /** True while a start request or a poll is still out. */
  get busy() {
    return this.card.root.dataset.state === "busy";
  }

  /** Show a spinner line; the provider's own button is disabled meanwhile. */
  showBusy(text) {
    this.card.root.dataset.state = "busy";
    this.card.error.hidden = true;
    this.card.progressText.textContent = text;
    this.card.progress.hidden = false;
    this.card.button.disabled = true;
  }

  /** Back to rest: no spinner, no error, the button usable again. */
  showIdle() {
    this.card.root.dataset.state = this.signedIn ? "signed-in" : "idle";
    this.card.progress.hidden = true;
    this.card.progressText.textContent = "";
    this.card.error.hidden = true;
    this.card.errorDetail.textContent = "";
    this.card.button.disabled = false;
  }

  /** A failure in plain words, with Retry focused so Enter tries again. */
  showError(detail) {
    this.poller.stop();
    this.card.root.dataset.state = "failed";
    this.card.progress.hidden = true;
    this.card.progressText.textContent = "";
    this.card.errorDetail.textContent = detail;
    this.card.error.hidden = false;
    this.card.button.disabled = false;
  }

  /** The job finished: let the panel re-read who is signed in. */
  settle() {
    this.poller.stop();
    this.showIdle();
    return Promise.resolve(this.deps.onSettled()).catch(() => {});
  }

  /** Stop polling without touching what is on screen (Back, re-render). */
  stop() {
    this.poller.stop();
    if (this.busy) this.showIdle();
  }

  /** Lock purge: no account name, typed value or message survives it. */
  purge() {
    this.poller.stop();
    this.signedIn = false;
    this.showIdle();
    this.card.account.textContent = "";
  }
}
