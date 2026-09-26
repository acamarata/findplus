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
 * Constraints: CSP forbids inline styles and inline handlers, so the buttons
 *              use the .btn classes and addEventListener, never onclick=.
 *              UAT6-N32: the primary action is "Connect an account" while no
 *              provider is signed in (a Devices list would be empty), else
 *              "Choose devices"; an unknown answer falls back to the latter.
 */
"use strict";

import { t } from "./i18n.js";
import { openDevices } from "./devices.js";
import { anyProviderSignedIn, openSignin } from "./poll_status.js";

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
