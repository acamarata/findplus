/*
 * Roving-tabindex keyboard navigation for the `.fp-tabs` tablist.
 *
 * Purpose    : ArrowLeft/ArrowRight/Home/End move focus AND activate a tab
 *              (the "automatic activation" variant of the WAI-ARIA tabs
 *              pattern) -- the tabs previously ignored arrow keys entirely
 *              (UAT U31), so a keyboard user had to Tab through every button
 *              one at a time with no way to jump to the last tab.
 * Inputs     : switchTab(tab) from main.js, which also owns aria-selected
 *              and the roving tabindex (set on click there, kept in sync
 *              here by re-reading the DOM rather than duplicating state).
 * Outputs    : wireTabsKeyboard() wires one keydown listener on `.fp-tabs`.
 * Constraints: Arrow keys wrap at both ends; Home/End jump to the first/last
 *              tab. Each key both moves focus and activates the tab, so a
 *              phone-tier click and an arrow key always land on the same
 *              state (main.js's switchTab() is the single source of truth).
 */
"use strict";

export function wireTabsKeyboard(switchTab) {
  const nav = document.querySelector(".fp-tabs");
  if (!nav) return;
  nav.addEventListener("keydown", (e) => {
    const tabs = Array.from(nav.querySelectorAll(".fp-tab"));
    const current = tabs.indexOf(document.activeElement);
    if (current === -1) return;
    let next = null;
    if (e.key === "ArrowRight") next = tabs[(current + 1) % tabs.length];
    else if (e.key === "ArrowLeft") next = tabs[(current - 1 + tabs.length) % tabs.length];
    else if (e.key === "Home") next = tabs[0];
    else if (e.key === "End") next = tabs[tabs.length - 1];
    if (!next) return;
    e.preventDefault();
    switchTab(next.dataset.tab);
    next.focus();
  });
}
