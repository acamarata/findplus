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

/** Each menu item clicks the topbar button it names; no handler is duplicated. */
function wireMoreMenu() {
  const btn = document.getElementById("btn-more");
  const menu = document.getElementById("fp-more-menu");
  if (!btn || !menu) return null;

  menu.querySelectorAll("[data-relays-to]").forEach((item) => {
    item.addEventListener("click", () => {
      menu.classList.add("hidden");
      btn.setAttribute("aria-expanded", "false");
      const target = document.getElementById(item.dataset.relaysTo);
      if (target) target.click();
    });
  });

  btn.addEventListener("click", () => {
    const nowHidden = menu.classList.toggle("hidden");
    btn.setAttribute("aria-expanded", String(!nowHidden));
  });
  return menu;
}

/** Keep the bar's visibility in step with the CSS that hides `.fp-tabs`. */
function syncVisibility(matches, menu) {
  if (tabbarEl) tabbarEl.classList.toggle("hidden", !matches);
  if (!matches && menu) menu.classList.add("hidden");
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
