/*
 * Google sign-in in the Find+ window (desktop app only).
 *
 * Purpose    : One Connect press: POST /api/auth/google/native/begin, hand the
 *              reply to the shell (`open_signin_window`), then follow the
 *              window until it is done. The shell's events (signin-progress,
 *              signin-result) make the card quick; GET .../native/progress is
 *              polled the whole time as the source of truth, so a missed event
 *              never strands the card. The unlock step runs in the same window.
 *              A block shows the fallback ladder's next step (contract §3.6).
 * Inputs     : The Google card, deps from panel.js, and hooks { settle,
 *              useChrome, showSteps } from google_flow.js.
 * Outputs    : DOM via google_native_view.js; hooks.settle() once connected,
 *              then focus on the card's result line.
 * Constraints: Never sees a token or a key (the shell posts those). A 401 on
 *              begin means the lock screen is up: stop quietly. A generation
 *              counter drops answers that land after Cancel, a lock or a new
 *              start; the daemon's flow id drops news from another window
 *              (google_native_flow_id.js). The daemon's progress is the truth
 *              (contract §3.8): a window still working is followed, never
 *              replaced. Specs: in-app-login.md §2.1, §3.4, §7; the contract.
 */
"use strict";

import { t } from "../i18n.js";
import { describeError } from "./job_poller.js";
import { closeSigninWindow, listenNative, openSigninWindow } from "./native_bridge.js";
import { isLive, paintNative } from "./google_native_view.js";
import { beginBody, isWindowOpen, sameFlow } from "./google_native_flow_id.js";

const ROUTE = "/api/auth/google/native";
/** The shell's progress phases, in the card's words. */
const EVENT_PHASE = { starting: "connecting", waiting: "waiting", finishing: "finishing",
  unlock: "needs_unlock" };
/** The window closes itself after 10 minutes; the card gives up a minute later. */
const DEFAULT_LIMIT_S = 660;

function pollMs() {
  return window.__FP_TEST_NATIVE_POLL_MS__ || 1000;
}

export class GoogleNativeFlow {
  constructor(card, deps, hooks) {
    this.card = card;
    this.deps = deps;
    this.hooks = hooks;
    this.phase = "idle";
    this.mode = "signin";
    this.generation = 0;
    this.timer = null;
    this.restMessage = "";
    this.startWith = "window";
    this.signedIn = false;
    this.flow = null;
    this.wire();
    this.ready = Promise.all([
      listenNative("signin-progress", (p) => this.onEvent(p)),
      listenNative("signin-result", (r) => this.onResult(r)),
    ]);
  }

  wire() {
    const { card } = this;
    card.nativeConnect.addEventListener("click", () => this.start("signin"));
    card.nativeRetry.addEventListener("click", () => this.start(this.mode));
    card.nativeWindowAgain.addEventListener("click", () => this.start("signin"));
    card.nativeShow.addEventListener("click", () => this.show());
    card.nativeCancel.addEventListener("click", () => this.cancel());
    card.nativePrefer.addEventListener("click", () => this.preferChrome());
    card.nativeChrome.addEventListener("click", () => this.hooks.useChrome());
    card.nativePaste.addEventListener("click", () => this.hooks.showSteps());
  }

  paint(view) {
    this.phase = paintNative(this.card, view);
  }

  /**
   * The resting state, from GET /api/auth/status: `google_native` (the
   * window's progress) and whether Google is connected. Connected rests as
   * "success" (no button: the card shows the account and its chips).
   */
  renderRest(native, signedIn = this.signedIn) {
    this.signedIn = !!signedIn;
    this.startWith = native && native.start_with === "helper" ? "helper" : "window";
    if (isLive(this.phase) || ["error", "blocked_embedded"].includes(this.phase)) return;
    let phase = this.startWith === "helper" ? "helper_first" : "idle";
    if (this.signedIn) phase = "success";
    this.paint({ phase, message: phase === "success" ? "" : this.restMessage });
  }

  /** Begin, open the window, follow it. `mode` is "signin" or "unlock". */
  async start(mode) {
    if (isLive(this.phase)) return this.show();
    this.mode = mode;
    this.restMessage = "";
    const mine = ++this.generation;
    this.flow = null;
    this.paint({ phase: "connecting" });
    let begin;
    try {
      begin = await this.deps.postJson(`${ROUTE}/begin`, beginBody(mode));
    } catch (err) {
      if (mine !== this.generation) return;
      if (err.status === 401) return this.toRest();
      if (isWindowOpen(err)) return this.adopt(mine, err.body);
      return this.fail((err.body && err.body.detail) || describeError(err));
    }
    if (mine !== this.generation) return;
    this.flow = (begin && begin.flow) || null;
    try {
      await openSigninWindow("google", mode, begin);
    } catch (_err) {
      if (mine !== this.generation) return;
      this.postCancel();
      return this.fail(t("signin.native.openFailed"));
    }
    if (mine !== this.generation) return;
    if (this.phase === "connecting") {
      this.paint({ phase: "waiting", message: t(this.waitingKey("opened")) });
    }
    const limit = (begin && begin.window && begin.window.timeout_seconds) || DEFAULT_LIMIT_S - 60;
    this.watch(mine, limit + 60);
  }

  /** A window is still working (409 window_open): follow it and bring it forward. */
  adopt(mine, body) {
    this.flow = body.flow || null;
    if (body.mode === "unlock") this.mode = "unlock";
    this.paint({ phase: "waiting", message: t(this.waitingKey("waiting")) });
    this.show();
    this.watch(mine, DEFAULT_LIMIT_S);
  }

  waitingKey(kind) {
    if (this.mode === "unlock") {
      return kind === "opened" ? "signin.native.openedUnlock" : "signin.native.unlockWaiting";
    }
    return kind === "opened" ? "signin.native.openedWaiting" : "signin.native.waiting";
  }

  /** Poll progress until a terminal phase; the source of truth. */
  watch(mine, limitSeconds) {
    this.stopPoll();
    const until = Date.now() + limitSeconds * 1000;
    const tick = async () => {
      if (mine !== this.generation) return this.stopPoll();
      if (Date.now() > until) return this.fail(t("signin.native.timeout"));
      try {
        const progress = await this.deps.api(`${ROUTE}/progress`);
        if (mine === this.generation) this.apply(progress);
      } catch (err) {
        if (err.status === 401) this.stopPoll();
      }
    };
    this.timer = setInterval(tick, pollMs());
  }

  stopPoll() {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  /** One progress answer (contract §3.6). */
  apply(p) {
    if (!p || !isLive(this.phase) || !sameFlow(this.flow, p.flow)) return;
    switch (p.phase) {
      case "success": return this.finish();
      case "blocked_embedded": return this.blocked(p.message, p.fallback);
      case "error": return this.fail(p.message);
      case "cancelled": return this.cancelled();
      case "waiting": return this.step("waiting");
      case "finishing": return this.step("finishing");
      case "needs_unlock": return this.step("needs_unlock");
      default: return undefined; // idle/connecting: nothing new yet
    }
  }

  /** A non-terminal phase, painted only when it changes (announced once). */
  step(phase, note) {
    if (phase === this.phase && !note) return;
    const message = phase === "waiting" ? t(this.waitingKey("waiting")) : undefined;
    this.paint({ phase, message, note });
  }

  /** signin-progress from the shell. A window the tray opened is followed too. */
  onEvent(p) {
    if (!p || p.provider !== "google") return;
    if (!isLive(this.phase)) {
      this.mode = p.mode === "unlock" ? "unlock" : "signin";
      this.flow = p.flow || null;
      this.restMessage = "";
      this.paint({ phase: "connecting" });
      this.watch(++this.generation, DEFAULT_LIMIT_S);
    } else if (!sameFlow(this.flow, p.flow)) {
      return;
    }
    const phase = EVENT_PHASE[p.phase];
    if (phase) this.step(phase, p.stuck ? "signin.native.stuck" : undefined);
  }

  /**
   * signin-result from the shell: the window is gone. Its own flow's success
   * still lands after an error was shown (a retried token that went through).
   */
  async onResult(r) {
    if (!r || r.provider !== "google" || !sameFlow(this.flow, r.flow)) return;
    const late = this.phase === "error" && r.outcome === "success" && !!this.flow;
    if (!isLive(this.phase) && !late) return;
    if (r.outcome === "success") return this.finish();
    if (r.outcome === "cancelled") return this.cancelled();
    if (r.outcome === "timeout") return this.fail(t("signin.native.timeout"));
    if (r.outcome === "blocked_embedded") {
      const p = await this.deps.api(`${ROUTE}/progress`).catch(() => null);
      return this.blocked(p && p.message, p ? p.fallback : "use_helper");
    }
    return this.fail(r.message);
  }

  async finish() {
    this.stopPoll();
    this.generation++;
    this.paint({ phase: "success", message: "" });
    await this.hooks.settle();
    this.card.account.tabIndex = -1;
    this.card.account.focus();
  }

  blocked(message, fallback) {
    this.stopPoll();
    this.paint({ phase: "blocked_embedded", message: message || undefined, fallback });
  }

  fail(message) {
    this.stopPoll();
    this.paint({ phase: "error", message: message || undefined });
  }

  cancelled() {
    this.stopPoll();
    this.generation++;
    this.restMessage = t("signin.native.cancelled");
    this.phase = "idle";
    this.renderRest({ start_with: this.startWith });
  }

  /** Bring the open window to the front (never starts a new one while live). */
  show() {
    openSigninWindow("google", this.mode).catch(() => {});
  }

  async cancel() {
    this.cancelled();
    await this.postCancel();
  }

  /** Drop the daemon's state and ask the shell to close its window. */
  async postCancel() {
    try {
      await this.deps.postJson(`${ROUTE}/cancel`);
    } catch (_err) {
      // Best effort: the state may already be gone.
    }
    closeSigninWindow();
  }

  /** "Prefer your Chrome?": stop the window, start the helper. */
  async preferChrome() {
    await this.cancel();
    this.restMessage = "";
    this.renderRest({ start_with: this.startWith });
    this.hooks.useChrome();
  }

  toRest() {
    this.stopPoll();
    this.phase = "idle";
    this.renderRest({ start_with: this.startWith });
  }

  /** The card is going away (wizard Back/Next): stop polling and listening. */
  stop() {
    this.generation++;
    this.stopPoll();
    this.ready.then((offs) => offs.forEach((off) => off())).catch(() => {});
  }

  /** Lock purge: no state, message or poll survives. */
  purge() {
    this.generation++;
    this.stopPoll();
    this.restMessage = "";
    this.signedIn = false;
    this.phase = "idle";
    this.paint({ phase: "idle", message: "" });
  }
}
