/*
 * The Person page's tracker list: role icon, name, carry weight, and a chip for
 * what the tracker did today. Select Edit to change its role or weight.
 *
 * Purpose    : Show which trackers make up a person and how Find+ weighs them,
 *              and let the owner correct a guess (a bag that is always carried,
 *              a second pair of shoes that never leaves home).
 * Inputs     : The person's trackers (GET /api/people/{id}), the now answer
 *              (motion, supporters, dissenters, stale), open left-behind
 *              episodes, a name resolver and an `onChanged()` callback.
 * Outputs    : One <section class="person-card">; PUT /api/people/trackers/{id}
 *              on Save.
 * Constraints: createElement/textContent only. A chip says what was seen, never
 *              more: "Left at School" appears only for a confirmed or pending
 *              left-behind episode, "Moved without Zaid" only when the tracker
 *              moved and the rest of the person's trackers disagree.
 */
"use strict";

import { plural, t } from "./i18n.js";
import { renderBadge } from "./components/badge.js";
import { saveTracker } from "./person_api.js";
import { showAlert } from "./state.js";

const ROLES = ["phone", "watch", "collar", "wallet", "keys", "shoes", "bag", "jacket", "bike", "scooter", "tablet", "laptop", "car", "luggage", "other"];
const ICONS = {
  phone: "smartphone", watch: "watch", collar: "paw-print", wallet: "wallet", keys: "key", shoes: "footprints", bag: "backpack",
  jacket: "shirt", bike: "bike", scooter: "bike", tablet: "laptop", laptop: "laptop", car: "car", luggage: "luggage", other: "map-pin",
};

/** The chips one tracker earns today, as [{cls, text}]. Pure, so tests can read it. */
export function chipsFor(tracker, ctx) {
  const id = tracker.device_id;
  const move = (ctx.now && ctx.now.trackers || []).find((x) => x.device_id === id);
  const motion = move ? move.motion : "unknown";
  const episode = ctx.episodes.find((e) => e.device_id === id && e.state !== "cleared");
  if (motion === "stale" || (ctx.now && (ctx.now.stale || []).includes(id))) return [{ cls: "stale", text: t("person.chip.stale") }];
  if (episode) {
    const text = episode.state === "apart_pending" ? t("person.chip.pending")
      : episode.place_name ? t("person.chip.leftAt", { place: episode.place_name }) : t("person.chip.leftSpot");
    return [{ cls: "left", text }];
  }
  const apart = ctx.now && (ctx.now.dissenters || []).includes(id);
  if (motion === "carried" && apart) return [{ cls: "apart", text: t("person.chip.movedWithout", { name: ctx.name }) }];
  if (motion === "carried") return [{ cls: "carried", text: t("person.chip.carried") }];
  return [];
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function roleIcon(tracker, ctx) {
  const wrap = el("span", "person-role-icon");
  const device = (ctx.devices || []).find((d) => d.device_id === tracker.device_id);
  const role = tracker.role && ICONS[tracker.role] ? tracker.role : "other";
  wrap.appendChild(renderBadge({ icon: `lucide:${ICONS[role]}`, color: (device && device.color) || "#64748b", label: null, name: tracker.name, size: 28 }));
  return wrap;
}

function metaText(tracker, fixes) {
  const role = t(`people.role.${ROLES.includes(tracker.role) ? tracker.role : "other"}`);
  const weight = tracker.carry_weight == null && tracker.weight == null ? t("person.trackers.noWeight")
    : t("person.trackers.weight", { weight: Number(tracker.carry_weight ?? tracker.weight).toFixed(2).replace(/\.?0+$/, "") });
  return [role, weight, fixes == null ? "" : plural("person.trackers.fixes", fixes, { n: fixes })].filter(Boolean).join(" · ");
}

/** The inline editor: role, weight, Save, Cancel. */
function editor(tracker, ctx, close) {
  const form = el("form", "person-edit");
  const id = `pt-${tracker.device_id}`.replace(/[^A-Za-z0-9_-]/g, "_");
  const role = el("select");
  role.id = `${id}-role`;
  [["", t("person.trackers.roleAuto")], ...ROLES.map((r) => [r, t(`people.role.${r}`)])].forEach(([value, text]) => {
    const opt = el("option", "", text);
    opt.value = value;
    opt.selected = value === (tracker.role_source === "set" ? tracker.role : "");
    role.appendChild(opt);
  });
  const weight = el("input");
  weight.type = "number"; weight.id = `${id}-weight`; weight.min = "0"; weight.max = "1"; weight.step = "0.05";
  weight.value = tracker.carry_weight == null ? "" : String(tracker.carry_weight);
  weight.placeholder = tracker.weight == null ? "" : String(tracker.weight);
  const help = el("p", "person-hint", t("person.trackers.weightHelp", { name: ctx.name }));
  weight.setAttribute("aria-describedby", `${id}-help`);
  help.id = `${id}-help`;
  const save = el("button", "btn btn-tiny", t("person.trackers.save"));
  save.type = "submit";
  const cancel = el("button", "btn-secondary btn-tiny", t("person.trackers.cancel"));
  cancel.type = "button";
  cancel.addEventListener("click", close);
  form.append(field(role, t("person.trackers.role")), field(weight, t("person.trackers.weightLabel")), help, el("div", "person-edit-actions"));
  form.lastChild.append(save, cancel);
  form.addEventListener("submit", (e) => { e.preventDefault(); submit(tracker, ctx, { role, weight }, close); });
  return form;
}

function field(input, label) {
  const wrap = el("div", "fp-dialog-field");
  const lab = el("label", "", label);
  lab.htmlFor = input.id;
  wrap.append(lab, input);
  return wrap;
}

async function submit(tracker, ctx, inputs, close) {
  const body = { role: inputs.role.value || null, carry_weight: inputs.weight.value === "" ? null : Number(inputs.weight.value) };
  try {
    await saveTracker(tracker.device_id, body);
    showAlert(t("person.trackers.saved", { tracker: tracker.name }), "info");
    close();
    await ctx.onChanged();
  } catch (err) {
    if (err.message !== "Locked") showAlert(t("person.trackers.saveFailed", { tracker: tracker.name, message: err.message }), "err");
  }
}

function row(tracker, ctx) {
  const li = el("li", "person-tracker");
  li.dataset.deviceId = tracker.device_id;
  const main = el("div", "person-tracker-main");
  const text = el("div", "person-tracker-text");
  const name = el("span", "person-tracker-name", ctx.nameOf(tracker.device_id));
  text.append(name, el("span", "person-tracker-meta", metaText(tracker, ctx.fixes && ctx.fixes.get(tracker.device_id))));
  if (tracker.device_id === ctx.leadId) text.insertBefore(el("span", "person-chip person-chip--lead", t("person.trackers.lead")), name.nextSibling);
  const chips = el("span", "person-chips");
  chipsFor(tracker, ctx).forEach((c) => chips.appendChild(el("span", `person-chip person-chip--${c.cls}`, c.text)));
  const edit = el("button", "btn btn-tiny person-tracker-edit", t("common.edit"));
  edit.type = "button";
  edit.setAttribute("aria-label", t("person.trackers.edit", { tracker: ctx.nameOf(tracker.device_id) }));
  edit.setAttribute("aria-expanded", "false");
  main.append(roleIcon(tracker, ctx), text, edit);
  li.append(main, chips);
  edit.addEventListener("click", () => {
    const open = li.querySelector(".person-edit");
    if (open) { open.remove(); edit.setAttribute("aria-expanded", "false"); return; }
    li.appendChild(editor(tracker, ctx, () => { li.querySelector(".person-edit")?.remove(); edit.setAttribute("aria-expanded", "false"); edit.focus(); }));
    edit.setAttribute("aria-expanded", "true");
    li.querySelector("select").focus();
  });
  return li;
}

/** The trackers card. `ctx.trackers` is already ordered, best sighting first. */
export function trackersCard(ctx) {
  const section = el("section", "person-card person-trackers");
  section.appendChild(el("h3", "person-card-title", t("person.trackers.title")));
  if (!ctx.trackers.length) {
    section.appendChild(el("p", "person-note", t("person.trackers.none")));
    return section;
  }
  const list = el("ul", "person-tracker-list");
  ctx.trackers.forEach((tr) => list.appendChild(row(tr, ctx)));
  section.appendChild(list);
  return section;
}
