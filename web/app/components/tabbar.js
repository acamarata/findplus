/*
 * Bottom tab bar and the topbar "More" menu, both phone-tier only.
 *
 * Purpose    : Give the dashboard a reachable nav under 600px. The bar is a
 *              second set of buttons for the same four tabs the `.fp-tabs`
 *              nav already drives, and the More menu relays clicks to the
 *              topbar buttons CSS hides at that width.
 * Inputs     : main.js's switchTab(tab); the i18n catalog for the tab labels;
 *              #btn-more and #fp-more-menu, which live in index.html.
 * Outputs    : A <nav class="fp-tabbar"> inserted immediately after .fp-tabs,
 *              and the wiring that opens/closes #fp-more-menu.
 * Constraints: Tab switching is NOT reimplemented here — switchTab() is the
 *              one source of truth, and each More-menu item clicks the
 *              original topbar button rather than copying its handler. Every
 *              element is built from nodes, never an innerHTML template.
 */
"use strict";

import { t } from "../i18n.js";
import { switchTab } from "../main.js";

/** The phone-tier media query. CSS owns which nav is visible; this mirrors it. */
const PHONE = "(max-width: 599px)";

const SVG_NS = "http://www.w3.org/2000/svg";

/** UAT2 U26: emoji render inconsistently across platforms/fonts; the app's
 * own Lucide sprite (main.js's loadIconSprite(), same symbols icon-picker.js
 * and badge.js draw from) is already bundled and in the page at boot. */
const TABS = [
  { tab: "dashboard", icon: "lucide-house", labelKey: "common.tabDashboard" },
  { tab: "places", icon: "lucide-map-pin", labelKey: "common.tabPlaces" },
  { tab: "groups", icon: "lucide-users", labelKey: "common.tabGroups" },
  { tab: "alerts", icon: "lucide-bell", labelKey: "common.tabAlerts" },
];

let tabbarEl = null;

/** A sprite `<use>` reference, aria-hidden: the button's own text label
 * (never hidden) is what gives it its accessible name. */
function tabIcon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "20");
  svg.setAttribute("height", "20");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("fp-tabbar-icon");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#${name}`);
  svg.appendChild(use);
  return svg;
}

function tabButton(entry) {
  const btn = document.createElement("button");
  btn.type = "button";
  // NOT `data-tab`: the existing browser suite selects tabs with a bare
  // `button[data-tab="..."]`, and a second matching button makes every one of
  // those selectors ambiguous. The bar drives switchTab() directly anyway.
  btn.dataset.tabbarTab = entry.tab;
  const label = document.createElement("span");
  label.textContent = t(entry.labelKey);
  btn.append(tabIcon(entry.icon), label);
  btn.addEventListener("click", () => {
    switchTab(entry.tab);
    markCurrent(entry.tab);
  });
  return btn;
}

/** `aria-current="page"` is how a screen reader hears which tab is showing. */
function markCurrent(tab) {
  if (!tabbarEl) return;
  tabbarEl.querySelectorAll("button").forEach((btn) => {
    if (btn.dataset.tabbarTab === tab) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });
}

/** The open menu's own Escape/outside-click listeners, or null while closed --
 *  module-scoped so closeMoreMenu() can remove exactly the pair openMoreMenu()
 *  added, however the menu ends up closing. */
let menuKeydown = null;
let menuOutsideClick = null;

/**
 * UAT3 N22: the menu used to stay open after Escape and after tapping
 * outside it -- neither had a handler. Closing always drops both listeners
 * first, so a second close (e.g. Escape after an outside click already
 * closed it) is a harmless no-op instead of stacking duplicate handlers.
 */
function closeMoreMenu(btn, menu, { restoreFocus = true } = {}) {
  menu.classList.add("hidden");
  btn.setAttribute("aria-expanded", "false");
  if (menuKeydown) { document.removeEventListener("keydown", menuKeydown); menuKeydown = null; }
  if (menuOutsideClick) { document.removeEventListener("click", menuOutsideClick); menuOutsideClick = null; }
  if (restoreFocus) btn.focus();
}

function openMoreMenu(btn, menu) {
  menu.classList.remove("hidden");
  btn.setAttribute("aria-expanded", "true");
  menuKeydown = (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    closeMoreMenu(btn, menu);
  };
  menuOutsideClick = (event) => {
    if (menu.contains(event.target) || event.target === btn) return;
    closeMoreMenu(btn, menu);
  };
  document.addEventListener("keydown", menuKeydown);
  document.addEventListener("click", menuOutsideClick);
}

/** Each menu item clicks the topbar button it names; no handler is duplicated. */
function wireMoreMenu() {
  const btn = document.getElementById("btn-more");
  const menu = document.getElementById("fp-more-menu");
  if (!btn || !menu) return null;

  menu.querySelectorAll("[data-relays-to]").forEach((item) => {
    item.addEventListener("click", () => {
      // A deliberate menu choice, not a dismissal -- focus follows the
      // relayed action (e.g. the Settings dialog's own trap) rather than
      // snapping back to the More button.
      closeMoreMenu(btn, menu, { restoreFocus: false });
      const target = document.getElementById(item.dataset.relaysTo);
      if (target) target.click();
    });
  });

  // The outside-click listener above is attached synchronously by
  // openMoreMenu(), so this SAME click's bubble to `document` must never
  // reach it -- stopPropagation() keeps the click that opens the menu from
  // being read as a click that dismisses it a moment later.
  btn.addEventListener("click", (event) => {
    event.stopPropagation();
    if (menu.classList.contains("hidden")) openMoreMenu(btn, menu);
    else closeMoreMenu(btn, menu, { restoreFocus: false });
  });
  return menu;
}

/** Keep the bar's visibility in step with the CSS that hides `.fp-tabs`. */
function syncVisibility(matches, menu) {
  if (tabbarEl) tabbarEl.classList.toggle("hidden", !matches);
  if (!matches && menu && !menu.classList.contains("hidden")) {
    closeMoreMenu(document.getElementById("btn-more"), menu, { restoreFocus: false });
  }
}

export function initTabbar() {
  const tabs = document.querySelector(".fp-tabs");
  if (!tabs || tabbarEl) return;

  tabbarEl = document.createElement("nav");
  tabbarEl.className = "fp-tabbar hidden";
  tabbarEl.setAttribute("aria-label", t("common.sectionsNavLabel"));
  TABS.forEach((entry) => tabbarEl.appendChild(tabButton(entry)));
  tabs.insertAdjacentElement("afterend", tabbarEl);
  markCurrent("dashboard");

  const menu = wireMoreMenu();
  const query = window.matchMedia(PHONE);
  syncVisibility(query.matches, menu);
  query.addEventListener("change", (e) => syncVisibility(e.matches, menu));
}
