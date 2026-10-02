/*
 * A pane's own error state: what failed, in plain words, and a Retry button.
 *
 * Purpose    : The timeline and the Groups tab used to swallow a failed load and
 *              keep (or show nothing but) the previous content, so a failure
 *              looked like a quiet day or an empty list. This builds the one
 *              "error" state of the seven UI states, shared by both panes.
 * Inputs     : `title` and `message` (already translated), `retryLabel` and the
 *              `onRetry` callback.
 * Outputs    : A <div class="empty empty-state" data-pane-error role="alert">.
 * Constraints: Built with createElement/textContent only. The Retry button is a
 *              real button, so it is keyboard reachable with no extra wiring.
 */
"use strict";

import { t } from "./i18n.js";

/** The error pane element; `onRetry` runs when the user presses Retry. */
export function paneError({ title, message, onRetry }) {
  const wrap = document.createElement("div");
  wrap.className = "empty empty-state";
  wrap.dataset.paneError = "1";
  wrap.setAttribute("role", "alert");
  const heading = document.createElement("p");
  heading.className = "empty-title";
  heading.textContent = title;
  const lead = document.createElement("p");
  lead.className = "empty-lead";
  lead.textContent = message;
  const row = document.createElement("div");
  row.className = "empty-actions";
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "btn";
  retry.textContent = t("common.retry");
  retry.addEventListener("click", () => onRetry());
  row.appendChild(retry);
  wrap.append(heading, lead, row);
  return wrap;
}
