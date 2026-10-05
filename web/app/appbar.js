/*
 * The app bar actions: Poll now, Add (menu), Devices, Settings, Lock.
 *
 * Purpose    : One row of icon+label buttons in the top bar, all built with
 *              components/button.js. "Add" is the primary button and opens a
 *              small menu: Place, Person, Group. Each item runs the flow the
 *              dashboard already had (the add-place dialog, the person editor
 *              in create mode, the add-group dialog); nothing is reimplemented.
 * Inputs     : The #fp-appbar-actions host in index.html (it already holds
 *              #btn-more, the phone-tier menu button).
 * Outputs    : Buttons with the ids the rest of the app already wires:
 *              #btn-poll (devices.js), #btn-devices (devices.js),
 *              #btn-settings (settings.js), #btn-lock (lock.js), plus
 *              #btn-add and its menu #fp-add-menu whose items are
 *              #fp-add-place, #fp-add-person and #fp-add-group (the phone
 *              More menu relays clicks to those three).
 * Constraints: mountAppBar() runs synchronously at the start of main(), before
 *              the catalog loads and before wireControls(): labels carry
 *              `labelKey`, so applyStaticI18n() fills them afterwards.
 */
"use strict";

import { button } from "./components/button.js";

const $ = (id) => document.getElementById(id);

function clickById(id) {
  const target = $(id);
  if (target) target.click();
}

/** After a person is added: show them in the People tab. */
async function personAdded() {
  const main = await import("./main.js");
  const groups = await import("./groups.js");
  await groups.loadGroups();
  main.switchTab("people");
  window.dispatchEvent(new CustomEvent("findplus:people-changed"));
}

async function addPerson() {
  const editor = await import("./person_editor.js");
  await editor.openPersonCreate(personAdded);
}

const ADD_ITEMS = [
  { id: "fp-add-place", icon: "lucide-map-pin", key: "shell.addPlace", fallback: "Place", run: () => clickById("fp-add-place-btn") },
  { id: "fp-add-person", icon: "lucide-user", key: "shell.addPerson", fallback: "Person", run: addPerson },
  { id: "fp-add-group", icon: "lucide-users", key: "shell.addGroup", fallback: "Group", run: () => clickById("fp-add-group-btn") },
];

function menuItem(item, close) {
  const el = button({ label: item.fallback, labelKey: item.key, icon: item.icon.slice(7), variant: "ghost", id: item.id, attrs: { role: "menuitem" } });
  el.addEventListener("click", () => { close(); item.run(); });
  return el;
}

/** The Add button and its menu: Escape and an outside click close it, arrows move. */
function buildAddMenu() {
  const wrap = document.createElement("span");
  wrap.className = "fp-add-wrap";
  const trigger = button({
    label: "Add", labelKey: "shell.btnAdd", icon: "plus", variant: "primary", id: "btn-add",
    attrs: { "aria-haspopup": "menu", "aria-expanded": "false", "aria-controls": "fp-add-menu" },
  });
  const menu = document.createElement("div");
  menu.id = "fp-add-menu";
  menu.className = "fp-add-menu hidden";
  menu.setAttribute("role", "menu");
  menu.dataset.i18nAttr = "aria-label:shell.addMenuLabel";
  menu.setAttribute("aria-label", "Add to Find+");
  const close = (restore = true) => {
    menu.classList.add("hidden");
    trigger.setAttribute("aria-expanded", "false");
    if (restore) trigger.focus();
  };
  const items = ADD_ITEMS.map((item) => menuItem(item, () => close(false)));
  menu.append(...items);
  const open = () => {
    menu.classList.remove("hidden");
    trigger.setAttribute("aria-expanded", "true");
    items[0].focus();
  };
  trigger.addEventListener("click", (e) => { e.stopPropagation(); if (menu.classList.contains("hidden")) open(); else close(); });
  menu.addEventListener("keydown", (e) => {
    const at = items.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); items[(at + 1) % items.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(at - 1 + items.length) % items.length].focus(); }
    else if (e.key === "Tab") close(false);
  });
  document.addEventListener("click", (e) => { if (!wrap.contains(e.target) && !menu.classList.contains("hidden")) close(false); });
  wrap.append(trigger, menu);
  return wrap;
}

/** Phone layout: "Map" opens or closes the map card, "Filters" the filter row. */
function wireToggle(buttonId, targetId, openClass) {
  const btn = $(buttonId);
  const target = $(targetId);
  if (!btn || !target) return;
  btn.addEventListener("click", () => {
    const open = target.classList.toggle(openClass);
    btn.setAttribute("aria-expanded", String(open));
    if (open && buttonId === "btn-map-toggle") window.dispatchEvent(new Event("resize"));
  });
}

/** Build the action row. Safe to call once; a second call is a no-op. */
export function mountAppBar() {
  const host = $("fp-appbar-actions");
  if (!host || $("btn-poll")) return;
  const more = $("btn-more");
  const row = [
    button({ label: "Poll now", labelKey: "common.btnPoll", titleKey: "common.btnPollTitle", icon: "refresh-cw", id: "btn-poll" }),
    buildAddMenu(),
    button({ label: "Devices", labelKey: "common.btnDevices", icon: "tag", id: "btn-devices" }),
    button({ label: "Settings", labelKey: "common.btnSettings", icon: "settings", id: "btn-settings" }),
    button({ label: "Lock", labelKey: "common.btnLock", titleKey: "common.btnLockTitle", icon: "lock", id: "btn-lock" }),
  ];
  row.forEach((node) => host.insertBefore(node, more));
  wireToggle("btn-map-toggle", "map-pane", "is-open");
  wireToggle("btn-filters-toggle", "fp-controls", "is-open");
  $("btn-lock").classList.add("hidden"); // lock.js / settings.js reveal it when a PIN is set
}
