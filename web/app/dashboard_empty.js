/*
 * Dashboard timeline empty state: nothing tracked at all.
 *
 * Purpose    : Build the "no devices tracked yet" placeholder with real
 *              Devices / Run setup buttons instead of plain-text names (U12
 *              gap audit row U13). Split out of timeline.js to stay under
 *              the PRI rule-7 300-line file cap.
 * Inputs     : None beyond the catalog (t()).
 * Outputs    : A <div class="empty"> with a message paragraph and two
 *              buttons; timeline.js appends it to #tracks.
 * Constraints: CSP forbids inline styles and inline handlers, so both
 *              buttons use the existing .btn/.btn-secondary classes and are
 *              wired with addEventListener, never onclick=.
 */
"use strict";

import { t } from "./i18n.js";
import { openDevices } from "./devices.js";

/** A real, clickable button, never a plain-text name pretending to be one. */
function emptyStateButton(label, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-secondary";
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

/** Nothing is tracked at all: say so in plain words, then offer the two ways
 * out -- open Devices to pick one, or run setup again from scratch. */
export function nothingTrackedEmptyState() {
  const wrap = document.createElement("div");
  wrap.className = "empty";
  const message = document.createElement("p");
  message.textContent = t("notices.dashboardEmpty");
  wrap.append(
    message,
    emptyStateButton(t("common.btnDevices"), () => openDevices()),
    emptyStateButton(t("setup.rerun"), () => { window.location.hash = "#/setup"; }),
  );
  return wrap;
}
