/*
 * One "We noticed this place" card and its inline Name it form.
 *
 * Purpose    : Show a suggestion with a mini map, then let the owner name it
 *              (name, kind, arrive-and-leave box) or dismiss it as "Not a place".
 * Inputs     : One candidate and callbacks {onSaved(place), onDismiss(candidate)}.
 * Outputs    : { li, destroy }. Saving POSTs /api/places with the spot's own
 *              coordinates and radius, and `notify: true` unless unticked.
 * Constraints: createElement/textContent only. Nothing is saved without Save.
 *              Home is preselected only when the suggestion was "Home?"; a
 *              kind the owner picked is never overwritten by the name guess.
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";
import { guessKind, KINDS } from "./places_kind.js";
import { miniMap } from "./places_noticed_map.js";
import { factsLine, guessTitle, usuallyLine } from "./places_noticed_text.js";

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

function kindSelect(c, id) {
  const select = el("select");
  select.id = id;
  KINDS.forEach((k) => {
    const opt = el("option", "", t(`places.kind.${k}`));
    opt.value = k;
    select.appendChild(opt);
  });
  select.value = c.kind_guess === "home" ? "home" : "other";
  select.addEventListener("change", () => { select.dataset.touched = "1"; });
  return select;
}

function field(labelText, input) {
  const row = el("div", "fp-dialog-field");
  const label = el("label", "", labelText);
  label.htmlFor = input.id;
  row.append(label, input);
  return row;
}

function body(c, name, kind, notify) {
  return {
    name: name.value.trim(),
    latitude: c.lat,
    longitude: c.lon,
    radius_meters: c.radius_m,
    kind: kind.value,
    notify: notify.checked,
  };
}

function buildForm(c, uid, { onSaved, close }) {
  const form = el("form", "pn-form");
  const name = el("input");
  name.type = "text"; name.id = `pn-name-${uid}`; name.required = true; name.maxLength = 64;
  const kind = kindSelect(c, `pn-kind-${uid}`);
  name.addEventListener("input", () => { if (!kind.dataset.touched) kind.value = guessKind(name.value); });
  const box = el("input");
  box.type = "checkbox"; box.checked = true;
  const notifyRow = el("label", "fp-notify-label");
  notifyRow.append(box, el("span", "", t("places.notify.label")));
  const status = el("p", "pn-status");
  status.setAttribute("role", "status");
  const save = el("button", "btn", t("places.noticed.save"));
  save.type = "submit";
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    save.disabled = true;
    try {
      onSaved(await api("/api/places", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body(c, name, kind, box)),
      }));
    } catch (err) {
      if (err.message !== "Locked") status.textContent = t("places.noticed.failed", { message: err.message });
      save.disabled = false;
    }
  });
  const actions = el("div", "pn-actions");
  actions.append(save, button(t("common.cancel"), "btn-secondary", close));
  form.append(field(t("places.nameLabel"), name), field(t("places.kind.label"), kind), notifyRow, status, actions);
  return { form, name };
}

export function suggestionCard(c, uid, { onSaved, onDismiss }) {
  const li = el("li", "pn-card");
  const mapHost = el("div", "pn-map");
  mapHost.setAttribute("role", "img");
  mapHost.setAttribute("aria-label", t("places.noticed.mapLabel", { lat: c.lat.toFixed(4), lon: c.lon.toFixed(4) }));
  const text = el("div", "pn-text");
  const title = el("h4", "pn-title", guessTitle(c));
  const actions = el("div", "pn-actions");
  const hold = el("div", "pn-form-hold");
  const nameIt = button(t("places.noticed.nameIt"), "btn btn-tiny", () => {
    const { form, name } = buildForm(c, uid, { onSaved, close: () => { hold.replaceChildren(); nameIt.hidden = false; } });
    nameIt.hidden = true;
    hold.replaceChildren(form);
    name.focus();
  });
  actions.append(nameIt, button(t("places.noticed.notAPlace"), "btn-secondary btn-tiny", () => onDismiss(c)));
  text.append(title, el("p", "pn-line", usuallyLine(c)), el("p", "pn-line pn-facts", factsLine(c)), actions, hold);
  li.append(mapHost, text);
  let mini = null;
  // The map needs a laid-out box; build it after the card is in the page.
  const mount = () => { if (!mini && mapHost.isConnected) mini = miniMap(mapHost, c.lat, c.lon, c.radius_m); };
  return { li, mount, destroy: () => { if (mini) mini.destroy(); mini = null; } };
}
