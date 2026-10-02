/*
 * "Whose is this?": trackers whose names say nothing about an owner.
 *
 * Purpose    : A tracker called "Pixel 11 Pro" has no owner word. Find+ lists it
 *              with a picker so one click puts it on the right person, or on a
 *              new one. Nothing is assigned until Add is pressed.
 * Inputs     : The `unassigned` list from GET /api/people/suggestions, the
 *              existing people, and `onAccept(body)`.
 * Outputs    : A <section class="ps-whose"> (or null when there is nothing to ask).
 * Constraints: createElement/textContent only. A new person's name is typed; it
 *              is not guessed.
 */
"use strict";

import { t } from "./i18n.js";

const NEW = "new";

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function body(tracker, choice, newName, people) {
  const members = [{ device_id: tracker.device_id, role: tracker.role || undefined }];
  if (choice === NEW) return { action: "create", name: newName.trim(), kind: "person", group_id: null, members };
  const person = people.find((p) => String(p.id) === choice);
  return { action: "add", name: person.name, kind: person.kind, group_id: person.id, members };
}

function row(tracker, people, onAccept) {
  const li = el("li", "ps-whose-row");
  const id = `ps-whose-${tracker.device_id}`.replace(/[^A-Za-z0-9_-]/g, "_");
  const label = el("label", "", t("people.panel.whosePick", { tracker: tracker.name }));
  label.htmlFor = id;
  const select = el("select");
  select.id = id;
  const first = el("option", "", t("people.panel.whoseChoose"));
  first.value = "";
  select.appendChild(first);
  people.forEach((p) => { const o = el("option", "", p.name); o.value = String(p.id); select.appendChild(o); });
  const fresh = el("option", "", t("people.panel.whoseNew"));
  fresh.value = NEW;
  select.appendChild(fresh);
  const name = el("input");
  name.type = "text"; name.hidden = true; name.placeholder = t("people.panel.whoseNewName");
  name.setAttribute("aria-label", t("people.panel.whoseNewName"));
  const add = el("button", "btn btn-tiny", t("people.panel.whoseAdd"));
  add.type = "button"; add.disabled = true;
  const sync = () => {
    name.hidden = select.value !== NEW;
    add.disabled = !select.value || (select.value === NEW && !name.value.trim());
  };
  select.addEventListener("change", sync);
  name.addEventListener("input", sync);
  add.addEventListener("click", () => onAccept(body(tracker, select.value, name.value, people)));
  li.append(label, select, name, add);
  return li;
}

/** The "Whose is this?" section, or null when every tracker has an owner. */
export function unassignedSection(unassigned, people, onAccept) {
  if (!unassigned.length) return null;
  const section = el("section", "ps-whose");
  section.appendChild(el("h4", "ps-sub", t("people.panel.whoseTitle")));
  section.appendChild(el("p", "person-hint", t("people.panel.whoseLead")));
  const list = el("ul", "ps-whose-list");
  unassigned.forEach((tr) => list.appendChild(row(tr, people, onAccept)));
  section.appendChild(list);
  return section;
}
