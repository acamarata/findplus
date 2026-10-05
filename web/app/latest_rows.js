/*
 * One row of the Latest list: a person or a tracker.
 *
 * Purpose    : Draw the row, its Edit button and its click target. The text is the
 *              server's own: a person's "where" sentence and confidence come from the
 *              person engine (the same words the Person page uses).
 * Inputs     : A {person, now, stale} entry or a device row, and handlers
 *              {devices, onOpen, onEdit}.
 * Outputs    : personRow(entry, handlers) and trackerRow(device, handlers): <li> nodes.
 * Constraints: createElement/textContent only. The clickable part is a real button;
 *              Edit is a second, separate button (never nested). Stale people get
 *              `.is-stale` (dimmed, wording unchanged: "stale" never means "at home").
 */
"use strict";

import { t } from "./i18n.js";
import { fmtAgeMinutes, displayName } from "./state.js";
import { renderBadge } from "./components/badge.js";
import { button } from "./components/button.js";
import { confidenceChip } from "./person_head.js";
import { ageMinutes, placeName, trackerName } from "./latest_data.js";

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** A decorative badge for a person or tracker; letter fallback when there is no icon. */
export function rowBadge(spec, size) {
  const node = renderBadge({ icon: spec.icon || "letter", color: spec.color || "#64748b", label: spec.label || null, name: spec.name, size });
  node.setAttribute("aria-hidden", "true");
  return node;
}

/** The small pencil button every row (and the focus header) carries. */
export function editButton(label, onEdit) {
  const btn = button({ icon: "pencil", iconOnly: true, label, variant: "ghost", onClick: onEdit, attrs: { "data-act": "edit" } });
  btn.classList.add("fp-btn--xs");
  return btn;
}

function shell(kind, id, onOpen, openLabel) {
  const li = el("li", `fp-latest-row fp-latest-row--${kind}`);
  li.dataset[kind === "person" ? "personId" : "deviceId"] = String(id);
  const main = el("button", "fp-latest-main");
  main.type = "button";
  main.setAttribute("aria-label", openLabel);
  main.addEventListener("click", onOpen);
  li.appendChild(main);
  return { li, main };
}

/** "seen 7 min ago" or "no recent sighting". */
export function seenText(minutes) {
  return minutes == null ? t("latest.noSighting") : t("latest.seen", { age: fmtAgeMinutes(minutes) });
}

function trackerBadges(person, devices) {
  const wrap = el("span", "fp-latest-badges");
  const list = person.trackers || [];
  wrap.setAttribute("role", "img");
  wrap.setAttribute("aria-label", t("latest.trackersLabel", { names: list.map((tr) => tr.name).join(", ") }));
  list.forEach((tr) => {
    const d = devices.find((x) => x.device_id === tr.device_id) || {};
    wrap.appendChild(rowBadge({ icon: d.icon, color: d.color, label: d.label, name: tr.name }, 20));
  });
  return wrap;
}

/** A person: avatar, name, where sentence, confidence pill, their tracker badges. Click opens the Person page. */
export function personRow({ person, now, stale }, { devices, onOpen, onEdit }) {
  const { li, main } = shell("person", person.id, onOpen, t("latest.openPerson", { name: person.name }));
  li.classList.toggle("is-stale", stale);
  const text = el("span", "fp-latest-text");
  const head = el("span", "fp-latest-head");
  head.appendChild(el("span", "fp-latest-name", person.name));
  if (now) head.appendChild(confidenceChip(now.confidence));
  text.append(head, el("span", "fp-latest-where", now ? now.text : ""));
  if ((person.trackers || []).length) text.appendChild(trackerBadges(person, devices));
  main.append(rowBadge({ icon: person.icon, color: person.color, name: person.name }, 36), text);
  li.appendChild(editButton(t("latest.editPerson", { name: person.name }), onEdit));
  return li;
}

/** A tracker no person owns: badge, label, place or "Not at a saved place", and when it was seen. */
export function trackerRow(device, { onOpen, onEdit }) {
  const name = trackerName(device);
  const { li, main } = shell("tracker", device.device_id, onOpen, t("latest.focusTracker", { name }));
  const place = placeName(device);
  const text = el("span", "fp-latest-text");
  text.append(
    el("span", "fp-latest-name", name),
    el("span", "fp-latest-where", place ? t("latest.atPlace", { place }) : t("latest.noPlace")),
    el("span", "fp-latest-seen", seenText(ageMinutes(device))),
  );
  main.append(rowBadge({ icon: device.icon, color: device.color, label: device.label, name: displayName(device) }, 36), text);
  li.appendChild(editButton(t("latest.editTracker", { name }), onEdit));
  return li;
}

/** Open the existing device editor for `device`; `after()` runs once its dialog closes (saved or not). */
export async function openDeviceEditor(device, after) {
  const { openEditDialog } = await import("./devices_dialog.js");
  openEditDialog(device.device_id, device);
  const dlg = document.getElementById("fp-device-dialog");
  if (dlg && after) dlg.addEventListener("close", () => setTimeout(after, 0), { once: true });
}
