/*
 * The Export popover on the dashboard filter row.
 *
 * Purpose    : Export is a rare task, so the row carries one quiet "Export"
 *              button; the format, scope, range and Download controls live in
 *              a small popover under it (spec dashboard-1.3 U35).
 * Inputs     : #btn-export-open, #export-pop (its controls keep their ids).
 * Outputs    : Toggles #export-pop[hidden] and aria-expanded; Escape and an
 *              outside click close it and return focus to the button.
 * Constraints: No export logic here; timeline.js still builds the URL.
 */
"use strict";

import { $ } from "./state.js";

/** Wire the opener once at boot. Returns nothing. */
export function wireExportPopover() {
  const opener = $("btn-export-open");
  const pop = $("export-pop");
  if (!opener || !pop) return;
  const set = (open) => {
    pop.hidden = !open;
    opener.setAttribute("aria-expanded", String(open));
  };
  opener.addEventListener("click", () => set(pop.hidden));
  $("btn-export").addEventListener("click", () => set(false));
  document.addEventListener("click", (e) => {
    if (!pop.hidden && !e.target.closest(".export-wrap")) set(false);
  });
  opener.closest(".export-wrap").addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !pop.hidden) { e.stopPropagation(); set(false); opener.focus(); }
  });
}
