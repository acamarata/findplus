/*
 * The member list inside the person editor: tick a tracker, then say what it is.
 *
 * Purpose    : One row per tracker. A ticked row shows a role (shoes, bag, keys,
 *              or "Fill in from the tracker name") and how often the person carries it (always, usually, sometimes).
 *              A tracker that already belongs to another person is listed
 *              switched off with that person's name, because a tracker has one
 *              owner.
 * Inputs     : The devices (GET /api/devices), every person (GET /api/people)
 *              and the person being edited.
 * Outputs    : { fieldset, collect() }. collect() gives one entry per ticked
 *              tracker: { device_id, role, carry_weight, changed }.
 * Constraints: createElement/textContent only. Untracked devices are listed
 *              switched off (Find+ never polls them).
 */
"use strict";

import { t } from "./i18n.js";
import { displayName } from "./state.js";
import { renderBadge } from "./components/badge.js";

const ROLES = ["phone", "watch", "collar", "wallet", "keys", "shoes", "bag", "jacket", "bike", "scooter", "tablet", "laptop", "car", "luggage", "other"];

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function roleSelect(current) {
  const select = el("select", "pe-role");
  select.setAttribute("aria-label", t("person.edit.role"));
  [["", t("person.trackers.roleAuto")], ...ROLES.map((r) => [r, t(`people.role.${r}`)])].forEach(([value, text]) => {
    const opt = el("option", "", text);
    opt.value = value;
    opt.selected = value === current;
    select.appendChild(opt);
  });
  return select;
}

/** How often the person carries a tracker, in words; the stored value is still the 0 to 1 weight. */
const WEIGHTS = [[1, "always"], [0.7, "usually"], [0.4, "sometimes"]];

function weightInput(current) {
  const select = el("select", "pe-weight");
  select.setAttribute("aria-label", t("person.trackers.weightLabel"));
  const options = [["", t("person.trackers.noWeight")], ...WEIGHTS.map(([v, key]) => [String(v), t(`personColours.weight.${key}`)])];
  // A weight set earlier outside the three words (CLI, API) is kept and shown as it is.
  if (current != null && !WEIGHTS.some(([v]) => v === current)) options.push([String(current), t("personColours.weight.custom", { value: current })]);
  options.forEach(([value, text]) => {
    const opt = el("option", "", text);
    opt.value = value;
    opt.selected = value === (current == null ? "" : String(current));
    select.appendChild(opt);
  });
  return select;
}

/** One row: checkbox, badge, name; role and weight once ticked. */
function row(device, tracker, owner) {
  const wrap = el("div", "pe-row");
  const label = el("label", "fp-member-row");
  const box = el("input");
  box.type = "checkbox"; box.dataset.deviceId = device.device_id;
  box.checked = Boolean(tracker);
  box.disabled = Boolean(owner) || !(device.is_tracked || tracker);
  label.classList.toggle("fp-member-row--off", box.disabled);
  const badge = el("span");
  badge.appendChild(renderBadge({ icon: device.icon || "letter", color: device.color, label: device.label, name: device.name, size: 16 }));
  label.append(box, badge, el("span", "", displayName(device)));
  if (owner) label.appendChild(el("span", "fp-field-hint", t("person.edit.belongsTo", { name: owner })));
  const extra = el("span", "pe-extra");
  const role = roleSelect(tracker && tracker.role_source === "set" ? tracker.role : "");
  const weight = weightInput(tracker ? tracker.carry_weight : null);
  extra.append(role, weight);
  extra.hidden = !box.checked;
  box.addEventListener("change", () => { extra.hidden = !box.checked; });
  wrap.append(label, extra);
  wrap._read = () => ({ role, weight, box, tracker });
  return wrap;
}

/** Build the member fieldset for `person` (null when adding is ever needed). */
export function buildMembers(devices, people, person) {
  const fieldset = el("fieldset", "pe-members");
  fieldset.appendChild(el("legend", "", t("person.edit.members")));
  fieldset.appendChild(el("p", "fp-field-hint", t("person.edit.membersHint")));
  const mine = new Map(((person && person.trackers) || []).map((x) => [x.device_id, x]));
  const owners = new Map();
  people.filter((p) => !person || p.id !== person.id).forEach((p) => p.trackers.forEach((x) => owners.set(x.device_id, p.name)));
  const list = el("div", "pe-list");
  const shown = devices.filter((d) => d.is_tracked || mine.has(d.device_id));
  const rows = shown.map((d) => row(d, mine.get(d.device_id), owners.get(d.device_id)));
  rows.forEach((r) => list.appendChild(r));
  if (!rows.length) list.appendChild(el("p", "fp-field-hint", t("person.edit.noDevices")));
  fieldset.appendChild(list);
  const collect = () => rows.map((r) => r._read()).filter((x) => x.box.checked).map((x) => {
    const role = x.role.value || null;
    const weight = x.weight.value === "" ? null : Number(x.weight.value);
    const was = x.tracker;
    const changed = !was || role !== (was.role_source === "set" ? was.role : null) || weight !== (was.carry_weight ?? null);
    return { device_id: x.box.dataset.deviceId, role, carry_weight: weight, changed, isNew: !was };
  });
  return { fieldset, collect };
}
