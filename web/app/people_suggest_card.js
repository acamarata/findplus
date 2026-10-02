/*
 * One "We found a person" card: who Find+ thinks it is, and what you can say.
 *
 * Purpose    : Show a suggestion in plain words ("Zaid (4 trackers: Bag, Bike,
 *              Shoes Red, Shoes White)") with the answers a person actually
 *              needs: Accept, Edit members, Not a person, It's a pet. A single
 *              word with no role word ("Meong") asks "person or pet?" first.
 * Inputs     : One suggestion from GET /api/people/suggestions, the trackers
 *              that could join it, and callbacks `onAccept(body)`/`onDismiss(key)`.
 * Outputs    : A <li class="ps-card">. It never calls the API itself.
 * Constraints: createElement/textContent only. Nothing here applies a
 *              suggestion: every change waits for a click. A low-confidence
 *              guess (the name is also a colour or brand) says so on the card.
 */
"use strict";

import { plural, t } from "./i18n.js";

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(label, cls, onClick) {
  const b = el("button", cls, label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

/** The request body that accepts `s` as `kind` with `members` ({device_id, role}). */
export function acceptBody(s, kind, members = s.members) {
  return { action: s.action, name: s.name, kind, group_id: s.group_id, members: members.map((m) => ({ device_id: m.device_id, role: m.role })) };
}

/** The title line: composed for a new person, the server's own sentence for convert/add. */
export function titleOf(s) {
  if (s.action !== "create") return s.preview;
  const names = s.members.map((m) => m.name).join(", ");
  return plural("people.panel.cardTitle", s.members.length, { name: s.name, n: s.members.length, names });
}

function editor(s, pool, onAccept, close) {
  const form = el("form", "ps-edit");
  const name = el("input");
  name.type = "text"; name.value = s.name; name.id = `ps-name-${s.key}`;
  const kind = el("select");
  kind.id = `ps-kind-${s.key}`;
  ["person", "pet"].forEach((k) => { const o = el("option", "", t(`person.kind.${k}`)); o.value = k; o.selected = k === s.kind; kind.appendChild(o); });
  const boxes = el("fieldset", "ps-members");
  boxes.appendChild(el("legend", "", t("people.panel.editTrackers")));
  pool.forEach((m) => {
    const label = el("label", "fp-member-row");
    const box = el("input");
    box.type = "checkbox"; box.dataset.deviceId = m.device_id; box.dataset.role = m.role || "";
    box.checked = s.members.some((x) => x.device_id === m.device_id);
    label.append(box, el("span", "", m.name));
    boxes.appendChild(label);
  });
  const error = el("p", "fp-dialog-error");
  error.setAttribute("role", "alert");
  const save = button(t("people.panel.editSave"), "btn btn-tiny", () => {
    const picked = [...boxes.querySelectorAll("input:checked")].map((b) => ({ device_id: b.dataset.deviceId, role: b.dataset.role || undefined }));
    if (!picked.length || !name.value.trim()) { error.textContent = t("people.panel.editNone"); return; }
    onAccept({ ...acceptBody(s, kind.value, picked), name: name.value.trim() });
  });
  form.append(field(t("people.panel.editName"), name), field(t("people.panel.editKind"), kind), boxes, error, save, button(t("people.panel.editCancel"), "btn-secondary btn-tiny", close));
  form.addEventListener("submit", (e) => e.preventDefault());
  return form;
}

function field(label, input) {
  const wrap = el("div", "fp-dialog-field");
  const lab = el("label", "", label);
  lab.htmlFor = input.id;
  wrap.append(lab, input);
  return wrap;
}

/** The buttons: one set when the kind is known, another when Find+ must ask. */
function actions(s, ctx) {
  const row = el("div", "ps-actions");
  const kind = s.kind || "person";
  if (s.ask_kind) {
    row.append(
      button(t("people.panel.itsPerson"), "btn btn-tiny", () => ctx.onAccept(acceptBody(s, "person"))),
      button(t("people.panel.itsPet"), "btn btn-tiny", () => ctx.onAccept(acceptBody(s, "pet"))),
      button(t("people.panel.neither"), "btn-secondary btn-tiny", () => ctx.onDismiss(s.key)),
    );
    return row;
  }
  row.append(button(s.action === "add" ? t("people.panel.acceptAdd") : t("people.panel.accept"), "btn btn-tiny ps-accept", () => ctx.onAccept(acceptBody(s, kind))));
  if (s.action !== "add") row.append(button(t("people.panel.editMembers"), "btn-secondary btn-tiny", ctx.toggleEdit));
  row.append(button(t("people.panel.notPerson"), "btn-secondary btn-tiny", () => ctx.onDismiss(s.key)));
  if (s.action !== "add" && kind !== "pet") row.append(button(t("people.panel.itsPet"), "btn-secondary btn-tiny", () => ctx.onAccept(acceptBody(s, "pet"))));
  return row;
}

/** The card for `s`. `pool` is every tracker that could join it. */
export function suggestionCard(s, pool, ctx) {
  const li = el("li", "ps-card");
  li.dataset.key = s.key;
  li.appendChild(el("p", "ps-title", titleOf(s)));
  if (s.ask_kind) li.appendChild(el("p", "ps-question", t("people.panel.askKind", { name: s.name })));
  const warn = s.warning || (s.confidence === "low" ? t("people.panel.lowConfidence") : "");
  if (warn) li.appendChild(el("p", "ps-warn", warn));
  const bar = actions(s, {
    ...ctx,
    toggleEdit: () => {
      const open = li.querySelector(".ps-edit");
      if (open) { open.remove(); return; }
      li.appendChild(editor(s, pool, ctx.onAccept, () => li.querySelector(".ps-edit")?.remove()));
      li.querySelector(".ps-edit input").focus();
    },
  });
  li.appendChild(bar);
  return li;
}
