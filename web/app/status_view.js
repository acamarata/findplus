/*
 * The dashboard's status chrome: topbar device name, the service dot, the
 * four summary cards and the banner.
 *
 * Purpose    : Render one GET /api/status response. Split out of main.js,
 *              which sat at the 300-line cap (PRI rule 7), when UAT6-N06
 *              needed room for plain-language poll states.
 * Inputs     : /api/status; state.deviceFilter; state.devices (provider names).
 * Outputs    : #device-name, #live-dot, the #card-* values and #alert.
 * Constraints: No status code or server exception text reaches the screen:
 *              poll_status.js maps codes to catalog sentences. Every banner
 *              offers the in-app fix first; a terminal command is only ever a
 *              secondary hint (UAT6-N07).
 */
"use strict";

import { $, state, fmtTime, fmtDuration, showAlert } from "./state.js";
import { api } from "./api.js";
import { t, plural } from "./i18n.js";
import { anyProviderSignedIn, failedPollNotice, isFailedPoll, openSignin, shortStatus } from "./poll_status.js";

/** The topbar device name: the filtered tracker, or how many are tracked.
 * U30: the title tooltip spells out what "~72/hr" counts. */
function renderDeviceName(s) {
  const tracked = s.devices.filter((d) => d.is_tracked);
  const el = $("device-name");
  el.title = "";
  if (state.deviceFilter) {
    el.textContent = (s.devices.find((d) => d.device_id === state.deviceFilter) || {}).name || state.deviceFilter;
    return;
  }
  if (!tracked.length) { el.textContent = t("common.noDevicesTracked"); return; }
  el.textContent = plural("common.devicesTracked", tracked.length, { n: tracked.length, rate: s.requests_per_hour });
  el.title = t("common.devicesTrackedRateHint", { rate: s.requests_per_hour });
}

/** The service dot. Green only while polls run AND the last one worked:
 * it used to stay green while every poll failed (UAT6-N06). */
function renderPollerDot(s) {
  const dot = $("live-dot");
  let kind = "live";
  let title = t("common.pollerActive", { interval: s.poll_interval_minutes });
  if (!s.tracked_count) {
    kind = "idle";
    title = t("common.pollerIdle");
  } else if (!s.poller_running) {
    kind = "stale";
    title = t("common.pollerStale");
  } else if (isFailedPoll(s.last_poll)) {
    kind = "warn";
    title = t("common.pollerFailing");
  }
  dot.className = "dot " + kind;
  dot.title = title;
  dot.dataset.health = kind;
}

/** The four summary cards. With no observation yet every value reads as empty. */
function renderCards(s) {
  const latest = s.latest_observation;
  const empty = t("common.emptyValue");
  $("card-observed").textContent = latest ? fmtTime(latest.observed_at_local) : empty;
  $("card-observed-ago").textContent = latest
    ? t("common.observedAgo", { age: fmtDuration(latest.age_seconds), device: latest.device_name })
    : t("common.noObservationsYet");
  $("card-fetched").textContent = latest ? fmtTime(latest.fetched_at_local) : empty;
  $("card-lag").textContent = latest
    ? t("common.retrievalLag", { lag: fmtDuration(latest.retrieval_lag_seconds) })
    : empty;

  const run = s.last_successful_poll;
  $("card-poll").textContent = run ? fmtTime(run.started_at_local) : empty;
  $("card-poll-status").textContent = s.last_poll
    ? t("common.lastAttempt", { status: shortStatus(s.last_poll.status) })
    : t("common.noPollsYet");
  $("card-today").textContent = String(s.observations_today);
  $("card-total").textContent = t("common.totalOnRecord", { total: s.observations_total });
}

const signinAction = () => ({ label: t("pollStatus.actionConnect"), run: () => openSignin() });

/** Nothing tracked: sign in first if nobody is, else pick devices. */
async function nothingTrackedBanner() {
  const signedIn = await anyProviderSignedIn();
  if (state.locked) return;  // the lock screen went up while we asked
  if (signedIn === false) {
    showAlert(t("pollStatus.bannerNoAccount"), "warn", { action: signinAction() });
    return;
  }
  const devices = await import("./devices.js");
  showAlert(t("pollStatus.bannerNothingTracked"), "warn", {
    action: { label: t("pollStatus.actionChooseDevices"), run: () => devices.openDevices() },
  });
}

/** The banner, in priority order: a failed poll, nothing tracked, a stopped service. */
async function renderStatusAlert(s) {
  if (isFailedPoll(s.last_poll)) {
    const notice = failedPollNotice(s.last_poll);
    showAlert(notice.message, "err", notice.action === "signin" ? { action: signinAction() } : {});
  } else if (!s.tracked_count) {
    await nothingTrackedBanner();
  } else if (!s.poller_running) {
    showAlert(t("pollStatus.bannerServiceStale"), "warn", {
      action: { label: t("pollStatus.actionPollNow"), run: () => $("btn-poll").click() },
      hint: t("pollStatus.serviceStaleHint"),
    });
  } else {
    showAlert(null);
  }
}

export async function loadStatus() {
  try {
    const query = state.deviceFilter ? `?device_id=${encodeURIComponent(state.deviceFilter)}` : "";
    const s = await api(`/api/status${query}`);
    renderDeviceName(s);
    renderPollerDot(s);
    renderCards(s);
    await renderStatusAlert(s);
  } catch (err) {
    showAlert(t("common.apiUnreachable", { message: err.message }), "err");
  }
}
