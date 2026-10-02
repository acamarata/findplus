/*
 * Dashboard timeline empty state: nothing tracked at all.
 *
 * Purpose    : Build the "no devices tracked yet" placeholder with real
 *              buttons instead of plain-text names (U12 gap audit row U13).
 *              Split out of timeline.js to stay under the PRI rule-7
 *              300-line file cap.
 * Inputs     : The catalog (t()) and GET /api/auth/status (through
 *              poll_status.js's cached anyProviderSignedIn()).
 * Outputs    : A <div class="empty empty-state"> with a heading, one
 *              sentence and an action row; timeline.js appends it to #tracks.
 *              A second state lives here too (emptyDayState): trackers exist
 *              but the pane has no rows, and the reason differs (locked, no
 *              data yet, a quiet day), so each says its own thing.
 * Constraints: CSP forbids inline styles and inline handlers, so the buttons
 *              use the .btn classes and addEventListener, never onclick=.
 *              UAT6-N32: the primary action is "Connect an account" while no
 *              provider is signed in (a Devices list would be empty), else
 *              "Choose devices"; an unknown answer falls back to the latter.
 */
"use strict";

import { $, state, fmtDateTime } from "./state.js";
import { t } from "./i18n.js";
import { openDevices } from "./devices.js";
import { anyProviderSignedIn, openSignin, openUnlock } from "./poll_status.js";
import { awaitingActive, emptyKind, noSightingNames } from "./poll_cycle.js";

/** A real, clickable button, never a plain-text name pretending to be one. */
function emptyStateButton(label, onClick, primary) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = primary ? "btn" : "btn btn-secondary";
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

/** The action row for a signed-in (or unknown) install, or a signed-out one. */
function fillActions(row, lead, signedIn) {
  const rerun = emptyStateButton(t("setup.rerun"), () => { window.location.hash = "#/setup"; }, false);
  if (signedIn === false) {
    lead.textContent = t("notices.dashboardEmptyNoAccount");
    row.replaceChildren(
      emptyStateButton(t("pollStatus.actionConnect"), () => openSignin(), true),
      rerun,
    );
  } else {
    lead.textContent = t("notices.dashboardEmptyLead");
    row.replaceChildren(
      emptyStateButton(t("pollStatus.actionChooseDevices"), () => openDevices(), true),
      rerun,
    );
  }
}

/** Nothing is tracked at all: say so in plain words, then offer the way out. */
export function nothingTrackedEmptyState() {
  const wrap = document.createElement("div");
  wrap.className = "empty empty-state";
  const heading = document.createElement("p");
  heading.className = "empty-title";
  heading.textContent = t("notices.dashboardEmpty");
  const lead = document.createElement("p");
  lead.className = "empty-lead";
  const row = document.createElement("div");
  row.className = "empty-actions";
  wrap.append(heading, lead, row);
  // Filled once the (local, cached) account check answers, so the primary
  // button never swaps under a pointer. data-ready is the tests' signal.
  anyProviderSignedIn().then((signedIn) => {
    fillActions(row, lead, signedIn);
    row.dataset.ready = "1";
  });
  return wrap;
}

/** The paragraph + action row shared by the three "tracked but empty" states. */
function emptyShell(kind, titleText) {
  const wrap = document.createElement("div");
  wrap.className = "empty empty-state";
  wrap.dataset.emptyDay = kind;
  const title = document.createElement("p");
  title.className = "empty-title";
  title.textContent = titleText;
  const lead = document.createElement("p");
  lead.className = "empty-lead";
  const row = document.createElement("div");
  row.className = "empty-actions";
  wrap.append(title, lead, row);
  return { wrap, lead, row };
}

/** Why there is no data at all yet, from what the last poll cycle said. */
function noDataLead(s) {
  if (state.pollInFlight || (s && awaitingActive(s))) return t("live.noDataPolling");
  const runs = s ? noSightingNames(s).length : 0;
  if (runs && runs === (s.devices || []).filter((d) => d.is_tracked).length) {
    return t("live.noDataNoSighting");
  }
  return t("live.noDataWaiting", { interval: (s && s.poll_interval_minutes) || "" });
}

/**
 * The pane for tracked devices with nothing to list: locked, no data yet, or a
 * quiet day. Without a status yet it is the plain old sentence, marked so
 * refreshEmptyPane() swaps it once /api/status lands.
 */
export function emptyDayState() {
  const s = state.status;
  if (!s) {
    const plain = document.createElement("div");
    plain.className = "empty";
    plain.dataset.emptyDay = "pending";
    plain.textContent = t("timeline.emptyDay");
    return plain;
  }
  const kind = emptyKind(s);
  if (kind === "locked") {
    const { wrap, lead, row } = emptyShell(kind, t("live.lockedTitle"));
    lead.textContent = t("live.lockedLead");
    row.append(emptyStateButton(t("pollStatus.actionUnlock"), () => openUnlock(), true));
    return wrap;
  }
  if (kind === "nodata") {
    const { wrap, lead } = emptyShell(kind, t("live.noDataTitle"));
    lead.textContent = noDataLead(s);
    return wrap;
  }
  const { wrap, lead, row } = emptyShell(kind, t("timeline.emptyDay"));
  const latest = s.latest_observation;
  lead.textContent = latest ? t("live.quietLatest", { when: fmtDateTime(latest.observed_at_local) }) : "";
  if (latest) {
    row.append(emptyStateButton(t("live.showLatest"), () => $("btn-latest").click(), true));
  }
  return wrap;
}

/** Re-render the empty pane in place when a fresh status changes its reason. */
export function refreshEmptyPane() {
  const host = $("tracks");
  const current = host && host.children.length === 1 ? host.firstElementChild : null;
  if (!current || !current.dataset.emptyDay) return;
  const next = emptyDayState();
  if (next.dataset.emptyDay === current.dataset.emptyDay && next.textContent === current.textContent) return;
  current.replaceWith(next);
}
