/*
 * Place dialog: element construction.
 *
 * Purpose    : Build the <dialog> the add/edit-place flow drives. Split out
 *              of places_dialog.js at the PRI rule-7 300-line file cap, the
 *              same way groups_dialog_dom.js separates construction from
 *              groups_dialog.js's behavior.
 * Inputs     : The save and cancel handlers places_dialog.js owns.
 * Outputs    : { dlg, fields, colorGroup, locatorHost } -- fields carries
 *              every input by name, colorGroup and locatorHost are the two
 *              mount points places_dialog.js fills with the colour picker
 *              and the tracker/map-pick/address locator after this returns.
 * Constraints: Pure construction, no network, no module state. Every element
 *              is built with createElement/textContent, never raw markup,
 *              and every static string comes from the catalog through t().
 */
"use strict";

import { t } from "./i18n.js";

function button(text, onClick, className) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = text;
  if (className) btn.className = className;
  btn.addEventListener("click", onClick);
  return btn;
}

function field(type, attrs) {
  const el = document.createElement("input");
  el.type = type;
  Object.assign(el, attrs);
  return el;
}

/** A `.fp-dialog-field` row — the same wrapper the device/group editors use. */
function labeled(text, input, id) {
  const label = document.createElement("label");
  if (id) label.htmlFor = id;
  label.textContent = text;
  const wrap = document.createElement("div");
  wrap.className = "fp-dialog-field";
  wrap.append(label, input);
  return wrap;
}

function pickerGroup(legendText) {
  const group = document.createElement("fieldset");
  group.className = "fp-dialog-group";
  const legend = document.createElement("legend");
  legend.textContent = legendText;
  group.appendChild(legend);
  return group;
}

/** The name/lat/lon/radius/colour/confirmation inputs, built once.
 * N16: enter/exit each carry a `max` too -- places/repo.py rejects anything
 * outside 1-5, and a bare `min` let the spinner's up-arrow walk past that
 * into a 422 the dialog used to show verbatim. */
function buildPlaceFields() {
  const title = document.createElement("h2");
  title.id = "fp-place-dialog-title";
  const name = field("text", { id: "fp-place-name", required: true, maxLength: 80 });
  const lat = field("hidden", { id: "fp-place-lat" });
  const lon = field("hidden", { id: "fp-place-lon" });
  const radius = field("range", {
    id: "fp-place-radius", min: "50", max: "5000", step: "10", value: "200",
  });
  const color = field("hidden", { id: "fp-place-color" });
  // UAT7 N01: the initial attribute value, before fillDialog() (places_dialog.js)
  // overwrites it per place -- kept at D17's own default (1) so nothing ever
  // paints "2" first, even for the instant before JS runs.
  const enter = field("number", { id: "fp-place-enter", min: "1", max: "5", value: "1" });
  const exit = field("number", { id: "fp-place-exit", min: "1", max: "5", value: "2" });
  // UAT7-N12: a slider alone gave no precise readout and no way to type an
  // exact metre value -- a number box kept in sync with the slider both ways
  // (places_dialog.js) covers both. It shares the row's one visible <label>
  // (radiusRow, below), so it needs its own accessible name.
  const radiusNumber = field("number", {
    id: "fp-place-radius-number", min: "50", max: "5000", step: "10", value: radius.value,
  });
  radiusNumber.setAttribute("aria-label", t("places.radiusLabel"));
  const error = document.createElement("p");
  error.className = "fp-dialog-error";
  error.id = "fp-place-dialog-error";
  return { title, name, lat, lon, radius, color, enter, exit, radiusNumber, error };
}

function radiusRow(f) {
  const label = document.createElement("label");
  label.htmlFor = f.radius.id;
  label.textContent = t("places.radiusLabel");
  const wrap = document.createElement("div");
  wrap.className = "fp-dialog-field";
  wrap.append(label, f.radius, f.radiusNumber);
  return wrap;
}

/** Assemble the <dialog>/<form> around the built fields, leaving the locator
 * section and the colour picker as empty mount points for the caller. */
export function buildDialog({ onSave, onCancel }) {
  const f = buildPlaceFields();
  const colorGroup = pickerGroup(t("places.colorLabel"));
  const locatorHost = document.createElement("div");

  const dlg = document.createElement("dialog");
  dlg.id = "fp-place-dialog";
  // Names the dialog for a screen reader (same fix as the device/group editors).
  dlg.setAttribute("aria-labelledby", "fp-place-dialog-title");

  const form = document.createElement("form");
  form.method = "dialog";
  form.append(
    f.title,
    labeled(t("places.nameLabel"), f.name, f.name.id),
    f.lat,
    f.lon,
    f.color,
    locatorHost,
    radiusRow(f),
    colorGroup,
    labeled(t("places.enterConfirmations"), f.enter, f.enter.id),
    labeled(t("places.exitConfirmations"), f.exit, f.exit.id),
  );

  const footer = document.createElement("footer");
  footer.append(
    button(t("common.save"), onSave, "btn"),
    button(t("common.cancel"), onCancel, "btn-secondary"),
  );
  form.append(f.error, footer);
  dlg.appendChild(form);

  return { dlg, fields: f, colorGroup, locatorHost };
}
