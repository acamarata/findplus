/*
 * What the latest poll cycle did, read off one /api/status body.
 *
 * Purpose    : The dashboard used to look only at the single newest poll run.
 *              With 17 trackers that run is one tracker's, so the banner could
 *              not say "locked" while most of the others were, and a cycle that
 *              found nothing new was silent. This module reads every tracked
 *              device's own last run, groups the ones from the same cycle, and
 *              answers: which failure matters, why nothing new arrived, and
 *              which kind of empty the dashboard is showing.
 * Inputs     : The /api/status body (devices[].last_poll, last_poll,
 *              observations_today, tracked_count, poll_interval_minutes) and
 *              state.devices for labels.
 * Outputs    : Pure answers (arrays, strings, a kind id); no DOM, no fetch.
 * Constraints: "No recent sighting" is Find Hub having nothing to report, not an
 *              error: it is never listed with failures. Names are tracker
 *              labels, passed to textContent by every caller.
 */
"use strict";

import { state, displayName, fmtTime } from "./state.js";
import { t, plural } from "./i18n.js";
import { isFailedPoll } from "./poll_status.js";

/** Runs this close together (ms) belong to one poll cycle. */
const CYCLE_WINDOW_MS = 10 * 60 * 1000;
/** Names listed in a sentence before it says "and N more". */
const NAMES_SHOWN = 5;
/** Longest the dashboard waits for a poll it expects (ms). */
export const AWAIT_MAX_MS = 120000;

const GOOGLE_ID = "google-find-hub";

/** Failures that mean the whole account is stuck, worst first. */
const ACCOUNT_WIDE = ["needs_shared_key", "provider_unauthenticated", "auth_error"];

/** The tracked devices' own last runs from the newest cycle: [{device, run}]. */
export function cycleRuns(s) {
  const rows = (s.devices || [])
    .filter((d) => d.is_tracked && d.last_poll)
    .map((device) => ({ device, run: device.last_poll, at: Date.parse(device.last_poll.started_at_utc) }));
  const newest = rows.reduce((m, r) => Math.max(m, r.at), 0);
  return rows.filter((r) => newest - r.at <= CYCLE_WINDOW_MS);
}

/** A tracker's label, else the provider's name for it. */
function nameOf(device) {
  const own = (state.devices || []).find((d) => d.device_id === device.device_id);
  return displayName(own) || device.name || device.device_id;
}

/**
 * The run the banner should explain, or null when the poll is healthy.
 *
 * An account-wide failure (locked, signed out) in ANY device of the newest
 * cycle wins over a healthy newest run; every other failure is only reported
 * when the newest run itself failed, as before.
 */
export function bannerRun(s) {
  const failing = cycleRuns(s)
    .map((r) => r.run)
    .filter((run) => isFailedPoll(run) && !staleLock(s, run));
  for (const status of ACCOUNT_WIDE) {
    const hit = failing.find((run) => run.status === status);
    if (hit) return hit;
  }
  const last = s.last_poll;
  return isFailedPoll(last) && !staleLock(s, last) ? last : null;
}

/**
 * True for a "locked" run whose cause is already fixed: the daemon's own
 * provider_health no longer asks Google to be unlocked, though the account is
 * signed in (shared key present). The run is history; the next poll replaces it.
 * Without a Google row in provider_health nothing is known, so the run stays.
 */
export function staleLock(s, run) {
  if (!run || run.status !== "needs_shared_key") return false;
  const rows = s.provider_health || [];
  const google = rows.find((row) => (row.name || row.id) === GOOGLE_ID);
  return Boolean(google) && google.authenticated === true && google.attention === "none";
}

/** True when the account's own failure is the locked end-to-end key. */
export function isLocked(s) {
  const run = s && bannerRun(s);
  return Boolean(run) && run.status === "needs_shared_key";
}

/** Names of tracked devices whose last run found no location, label first. */
export function noSightingNames(s) {
  return cycleRuns(s).filter((r) => r.run.status === "no_location").map((r) => nameOf(r.device));
}

/** "A, B, C and 4 more" from a list of names. */
function listNames(names) {
  const shown = names.slice(0, NAMES_SHOWN).join(", ");
  const more = names.length - NAMES_SHOWN;
  return more > 0 ? `${shown} ${t("live.andMore", { n: more })}` : shown;
}

/** The sentence about the next attempt: the loop's real time, never a quoted interval. */
function nextAttempt(s) {
  if (s.next_poll_at) return t("live.zeroNewNext", { time: fmtTime(s.next_poll_at) });
  return s.poll_interval_minutes ? t("live.zeroNewEvery", { interval: s.poll_interval_minutes }) : "";
}

/**
 * Why the last cycle added nothing, in plain words; null when it did add
 * something, failed, or today already has observations (nothing to explain).
 * Find Hub re-sending an old fix is "no newer location", never "same place".
 * Trackers that timed out or failed are listed apart from the quiet ones.
 */
export function zeroNewMessage(s) {
  const runs = cycleRuns(s);
  if (!runs.length || bannerRun(s)) return null;
  const fresh = runs.reduce((n, r) => n + (r.run.observations_new || 0), 0);
  if (fresh > 0 || s.observations_today > 0) return null;
  const answered = runs.filter((r) => !isFailedPoll(r.run));
  const failed = runs.filter((r) => isFailedPoll(r.run)).map((r) => nameOf(r.device));
  const silent = answered.filter((r) => r.run.status === "no_location").map((r) => nameOf(r.device));
  let text;
  if (silent.length === answered.length) text = t("live.zeroNewAll", { n: answered.length });
  else if (silent.length) text = t("live.zeroNewSome", { names: listNames(silent) });
  else text = t("live.zeroNewSame");
  if (failed.length) text += " " + t("live.zeroNewFailed", { names: listNames(failed) });
  return `${text} ${nextAttempt(s)}`.trim();
}

/** Short tail for the "last attempt" card line: how many have no sighting. */
export function noSightingCount(s) {
  const n = noSightingNames(s).length;
  return n ? plural("live.noSightingCount", n, { n }) : "";
}

/**
 * Whether the dashboard is still waiting for the poll an unlock or sign-in
 * started. Ends (and clears the flag) once a newer run exists or time is up.
 */
export function awaitingActive(s) {
  const wait = state.awaitingPoll;
  if (!wait) return false;
  const newer = s.last_poll && s.last_poll.id !== wait.baseId;
  if (newer || Date.now() - wait.since > AWAIT_MAX_MS) {
    state.awaitingPoll = null;
    return false;
  }
  return true;
}

/** "Polling 17 trackers…" for this status. */
export function pollingMessage(s) {
  const n = (s && s.tracked_count) || (state.awaitingPoll && state.awaitingPoll.n) || 0;
  return plural("live.polling", n, { n });
}

/**
 * Which empty the dashboard is in: "locked" (the key is not unlocked), "nodata"
 * (nothing ever recorded) or "quiet" (data exists, not for this day).
 */
export function emptyKind(s) {
  if (s && isLocked(s)) return "locked";
  if (!s || !s.observations_total) return "nodata";
  return "quiet";
}
