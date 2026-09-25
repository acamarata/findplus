/*
 * Poll one sign-in job until it settles, and say why when it cannot.
 *
 * Purpose    : The one poll loop both sign-in flows use. Every way a poll can
 *              end turns into either a progress callback or a plain-words
 *              error: the job's own terminal state, a 404 (the daemon forgot
 *              the job), repeated failures to reach the daemon, or the
 *              client-side cap.
 * Inputs     : api() from api.js, a progress route and a job id.
 * Outputs    : onProgress(progress) per answer; onError(message) once.
 * Constraints: One interval at a time. stop() bumps a generation counter, so
 *              a response already in flight when the poll was stopped (a lock,
 *              a Back click, a re-render) is dropped instead of written into a
 *              card nobody is looking at. A 401 stops quietly: api.js has
 *              already put the lock screen up.
 */
"use strict";

import { t } from "../i18n.js";

/** The 2 s cadence the dashboard's own refresh uses. */
export const POLL_MS = 2000;
/**
 * 200 polls, about 6.5 minutes: longer than the daemon's own 5-minute cookie
 * wait plus a slow Chrome launch, so the server's own timeout message is the
 * one people normally see and this cap only catches a job that never ends.
 */
export const POLL_CAP = 200;
/** A single dropped request is noise; three in a row means the daemon is gone. */
const MAX_MISSES = 3;

/**
 * Real timing, read once per start(). A UI test that wants to reach POLL_CAP
 * without 200 real network round trips (page.clock can fast-forward the
 * clock, but not the real fetches a mocked route still has to answer) sets
 * window.__FP_TEST_POLL_MS__ / __FP_TEST_POLL_CAP__ with page.add_init_script
 * before the poll starts — the same override-a-window-flag pattern
 * window.__findplus_native uses. Unset in production, so behaviour there is
 * exactly POLL_MS/POLL_CAP.
 */
function pollMs() {
  return window.__FP_TEST_POLL_MS__ || POLL_MS;
}
function pollCap() {
  return window.__FP_TEST_POLL_CAP__ || POLL_CAP;
}

/** A thrown api() error in words a person can act on. */
export function describeError(err) {
  if (!err || err.status === undefined) return t("signin.error.unreachable");
  return err.message || t("signin.error.unknown");
}

export class JobPoller {
  constructor(api) {
    this.api = api;
    this.timer = null;
    this.generation = 0;
  }

  get running() {
    return this.timer !== null;
  }

  stop() {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    this.generation++;
  }

  start(path, jobId, { onProgress, onError }) {
    this.stop();
    const mine = this.generation;
    const url = `${path}?job_id=${encodeURIComponent(jobId)}`;
    const cap = pollCap();
    let ticks = 0;
    let misses = 0;
    const fail = (message) => {
      this.stop();
      onError(message);
    };
    this.timer = setInterval(async () => {
      if (++ticks > cap) return fail(t("signin.error.timeout"));
      try {
        const progress = await this.api(url);
        if (mine !== this.generation) return;
        misses = 0;
        onProgress(progress);
      } catch (err) {
        if (mine !== this.generation) return;
        if (err.status === 401) return this.stop();
        if (err.status === 404) return fail(t("signin.error.expired"));
        if (++misses >= MAX_MISSES) fail(describeError(err));
      }
    }, pollMs());
  }
}
