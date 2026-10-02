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
import { buildKindField } from "./places_kind.js";
import { buildNotifyField } from "./places_notify.js";

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
  const name = field("text", { id: "fp-place-name", required: true, maxLength: 64 });
  const lat = field("hidden", { id: "fp-place-lat" });
  const lon = field("hidden", { id: "fp-place-lon" });
  const radius = field("range", {
    id: "fp-place-radius", min: "50", max: "500", step: "10", value: "100",
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
    id: "fp-place-radius-number", min: "50", max: "5000", step: "1", value: "100",
  });
  radiusNumber.setAttribute("aria-label", t("places.radiusLabel"));
  const error = document.createElement("p");
  error.className = "fp-dialog-error";
  error.id = "fp-place-dialog-error";
  // UAT #9: where the place will be saved, in words, under the locator.
  const where = document.createElement("p");
  where.className = "fp-field-hint";
  where.id = "fp-place-where";
  // Edit only: how many alert rules lean on this place (set by showUsage()).
  // A radius under the recommended minimum says why that is a bad idea.
  const radiusWarn = document.createElement("p");
  radiusWarn.className = "fp-field-hint fp-radius-warn";
  radiusWarn.id = "fp-place-radius-warn";
  radiusWarn.hidden = true;
  const usage = document.createElement("p");
  usage.className = "fp-field-hint fp-place-usage";
  usage.id = "fp-place-usage";
  usage.hidden = true;
  return { title, name, lat, lon, radius, color, enter, exit, radiusNumber, error, where, usage, radiusWarn };
}

function radiusRow(f) {
  const label = document.createElement("label");
  label.htmlFor = f.radius.id;
  label.textContent = t("places.radiusLabel");
  const wrap = document.createElement("div");
  wrap.className = "fp-dialog-field";
  const hint = document.createElement("p");
  hint.className = "fp-field-hint";
  hint.id = "fp-place-radius-hint";
  hint.textContent = t("places.radiusHint", { min: RECOMMENDED_MIN_RADIUS });
  f.radius.setAttribute("aria-describedby", hint.id);
  wrap.append(label, f.radius, f.radiusNumber);
  const group = document.createElement("div");
  group.append(wrap, hint, f.radiusWarn);
  return group;
}

/** Smallest radius Find+ recommends (mirrors places/geofence.py's
 *  RECOMMENDED_MIN_RADIUS_METERS; a test pins the two together). */
export const RECOMMENDED_MIN_RADIUS = 100;

/** Show the "too small" reason while the radius is under the recommended minimum. */
export function updateRadiusWarning(f) {
  const small = radiusOf(f) < RECOMMENDED_MIN_RADIUS;
  f.radiusWarn.hidden = !small;
  f.radiusWarn.textContent = small ? t("places.radiusSmall", { min: RECOMMENDED_MIN_RADIUS }) : "";
}

/** The radius in metres: the number box is the truth (the slider stops at 500 m, the box at 5000 m). */
export function radiusOf(f) {
  return Number(f.radiusNumber.value);
}

/** Set both radius inputs; the slider clamps itself to its own 50-500 m range. */
export function setRadius(f, metres) {
  f.radiusNumber.value = String(metres);
  f.radius.value = String(metres);
}

/**
 * UAT7-N12: the slider and the number box stay in sync both ways. The slider
 * covers the sizes that matter (50 to 500 m, step 10: UAT 11 found a 50 to 5000
 * m track left every sensible value pinned at the far left); bigger places are
 * typed in the box, which allows up to 5000 m. Setting a range input's `.value`
 * clamps it for free. The box is only tidied on `change` (blur or Enter) so a
 * value mid-typed (e.g. "5" on the way to "500") is not fought keystroke by
 * keystroke. `onPreview` redraws the live circle on the map.
 */
export function wireRadius(f, onPreview) {
  const changed = () => {
    updateRadiusWarning(f);
    onPreview();
  };
  f.radius.addEventListener("input", () => {
    f.radiusNumber.value = f.radius.value;
    changed();
  });
  f.radiusNumber.addEventListener("input", () => {
    f.radius.value = f.radiusNumber.value;
    changed();
  });
  f.radiusNumber.addEventListener("change", () => {
    const wanted = Math.round(radiusOf(f));
    setRadius(f, Number.isFinite(wanted) && wanted > 0 ? Math.min(5000, Math.max(50, wanted)) : f.radius.value);
    changed();
  });
}

/** Assemble the <dialog>/<form> around the built fields, leaving the locator
 * section and the colour picker as empty mount points for the caller. */
export function buildDialog({ onSave, onCancel }) {
  const f = { ...buildPlaceFields(), kind: buildKindField(), notify: buildNotifyField() };
  const colorGroup = pickerGroup(t("places.colorLabel"));
  const locatorHost = document.createElement("div");

  const dlg = document.createElement("dialog");
  dlg.id = "fp-place-dialog";
  // Names the dialog for a screen reader (same fix as the device/group editors).
  dlg.setAttribute("aria-labelledby", "fp-place-dialog-title");

  const form = document.createElement("form");
  form.method = "dialog";
  // Two columns on a wide screen (who and where on the left, size and alerts on the right),
  // one on a phone. The footer stays in view whatever the height (UAT 21).
  const left = document.createElement("div");
  left.className = "fp-place-col";
  left.append(labeled(t("places.nameLabel"), f.name, f.name.id), f.kind.wrap, f.lat, f.lon, f.color, locatorHost, f.where);
  const right = document.createElement("div");
  right.className = "fp-place-col";
  right.append(
    radiusRow(f),
    f.usage,
    colorGroup,
    labeled(t("places.enterConfirmations"), f.enter, f.enter.id),
    labeled(t("places.exitConfirmations"), f.exit, f.exit.id),
    f.notify.wrap,
  );
  const cols = document.createElement("div");
  cols.className = "fp-place-cols";
  cols.append(left, right);
  form.append(f.title, cols);

  const footer = document.createElement("footer");
  footer.append(
    button(t("common.save"), onSave, "btn"),
    button(t("common.cancel"), onCancel, "btn-secondary"),
  );
  form.append(f.error, footer);
  dlg.appendChild(form);

  return { dlg, fields: f, colorGroup, locatorHost };
}
