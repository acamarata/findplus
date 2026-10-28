/*
 * Settings dialog: the section list (left rail on desktop, a chip row on a phone).
 *
 * Purpose    : One long form is hard to move around in. This builds a list of the
 *              dialog's sections from the page, scrolls to one on click, and marks
 *              the section being read as the user scrolls.
 * Inputs     : `.settings-section` blocks inside #settings-body (partials/settings.html);
 *              labels from the `settings.nav.*` catalog keys.
 * Outputs    : Buttons inside #settings-nav; aria-current="true" on the active one.
 * Constraints: createElement/textContent only. The nav is built once, on first call.
 *              Scrolling is smooth unless the viewer prefers reduced motion.
 */
"use strict";

import { $ } from "./state.js";
import { t } from "./i18n.js";

const SECTIONS = ["general", "signin", "people", "alerts", "lock", "updates", "backups", "about", "danger"];
/** How far below the top edge a section counts as "being read". */
const SPY_OFFSET = 48;

function setCurrent(nav, id) {
  for (const btn of nav.querySelectorAll("button")) {
    if (btn.dataset.section === id) btn.setAttribute("aria-current", "true");
    else btn.removeAttribute("aria-current");
  }
}

function activeSection(body) {
  const top = body.getBoundingClientRect().top + SPY_OFFSET;
  let current = SECTIONS[0];
  for (const id of SECTIONS) {
    const sec = $(`settings-sec-${id}`);
    if (sec && sec.getBoundingClientRect().top <= top) current = id;
  }
  // At the very bottom the last section may be too short to reach the offset.
  if (body.scrollTop + body.clientHeight >= body.scrollHeight - 2) current = SECTIONS[SECTIONS.length - 1];
  return current;
}

function goTo(body, nav, id) {
  const sec = $(`settings-sec-${id}`);
  if (!sec) return;
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const delta = sec.getBoundingClientRect().top - body.getBoundingClientRect().top;
  body.scrollTo({ top: body.scrollTop + delta, behavior: reduce ? "auto" : "smooth" });
  setCurrent(nav, id);
}

/** Build the section list and wire click and scroll. Safe to call more than once. */
export function wireSettingsNav() {
  const nav = $("settings-nav");
  const body = $("settings-body");
  if (!nav || !body || nav.childElementCount) return;
  for (const id of SECTIONS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "settings-nav-item";
    btn.dataset.section = id;
    btn.textContent = t(`settings.nav.${id}`);
    btn.addEventListener("click", () => goTo(body, nav, id));
    nav.append(btn);
  }
  body.addEventListener("scroll", () => setCurrent(nav, activeSection(body)), { passive: true });
  setCurrent(nav, SECTIONS[0]);
}

/** Scroll the form back to the top (called each time the dialog opens). */
export function resetSettingsNav() {
  const nav = $("settings-nav");
  const body = $("settings-body");
  if (!body) return;
  body.scrollTop = 0;
  if (nav) setCurrent(nav, SECTIONS[0]);
}
