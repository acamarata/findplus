/*
 * The Person page's standing notes: what alerts and "now" can and cannot say.
 *
 * Purpose    : The two honesty sentences every person surface carries: alerts
 *              inherit the network's delay, and a tracker with no recent
 *              sighting is stale, not at home and not left behind.
 * Inputs     : The catalog (honesty.alertsLatency, honesty.presenceStale).
 * Outputs    : One footer node.
 * Constraints: The sentences come from the catalog, which is generated from
 *              honesty.py; they are never paraphrased here.
 */
"use strict";

import { t } from "./i18n.js";

/** The footer under the page. */
export function honestyFooter() {
  const box = document.createElement("div");
  box.className = "person-notes";
  ["honesty.alertsLatency", "honesty.presenceStale"].forEach((key) => {
    const p = document.createElement("p");
    p.className = "notice small";
    p.textContent = t(key);
    box.appendChild(p);
  });
  return box;
}
