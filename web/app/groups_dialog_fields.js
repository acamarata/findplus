/*
 * Group dialog: individual field-row builders.
 *
 * Purpose    : The quorum/radius/stale-after/members rows the group dialog
 *              places into its form, plus the small createElement helpers
 *              (field/labeled/fieldHint) they share with buildDialog() in
 *              groups_dialog_dom.js. Split out at the PRI rule-7 300-line
 *              file cap (E13 loop-1 follow-up), the same way
 *              groups_dialog_dom.js came out of groups_dialog.js.
 * Inputs     : None (pure DOM construction) besides the translation catalog.
 * Outputs    : { select/input/wrap } tuples groups_dialog_dom.js's
 *              buildDialog() assembles into the form — same shapes as
 *              before the split.
 * Constraints: Every element is built with createElement/textContent, never
 *              raw markup; every static string comes from the catalog
 *              through t(), same as the rest of the dialog.
 */
"use strict";

import { t } from "./i18n.js";

const DEFAULT_RADIUS = "150";
const DEFAULT_STALE = "90";

export function field(type, attrs) {
  const el = document.createElement("input");
  el.type = type;
  Object.assign(el, attrs);
  return el;
}

/**
 * A `.fp-dialog-field` row: a real `<label for>` beside its control, never
 * text and input sharing one `<label>` (that pairing has no gap between them
 * and the two painted on top of each other — visual gate W3 finding). Same
 * wrapper devices_dialog.js's own `labeled()` builds, so one CSS rule in
 * components.css covers both dialogs' field rows.
 */
export function labeled(text, input, id) {
  const label = document.createElement("label");
  if (id) label.htmlFor = id;
  label.textContent = text;
  const wrap = document.createElement("div");
  wrap.className = "fp-dialog-field";
  wrap.append(label, input);
  return wrap;
}

/** A one-line `<p class="fp-field-hint">` under a field, e.g. the quorum,
 * radius and stale-after rows below (U21: plain-word help text). */
function fieldHint(text) {
  const hint = document.createElement("p");
  hint.className = "fp-field-hint";
  hint.textContent = text;
  return hint;
}

// value is validation.py's own grammar ("any"/"majority"/"all"/a number as a
// string) and is never changed; only the displayed option text is plain
// words (U21: raw "any/majority/all" read as unexplained jargon).
const QUORUM_LABEL_KEYS = {
  any: "groups.field.quorum_any", majority: "groups.field.quorum_majority", all: "groups.field.quorum_all",
};

export function quorumRow() {
  const select = document.createElement("select");
  select.id = "fp-group-quorum";
  for (const value of ["any", "majority", "all", "custom"]) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value === "custom"
      ? t("groups.field.quorum_custom")
      : t(QUORUM_LABEL_KEYS[value]);
    select.appendChild(opt);
  }
  const n = field("number", { id: "fp-group-quorum-n", min: "1", max: "20", value: "2", hidden: true });
  const wrap = document.createElement("div");
  wrap.append(labeled(t("groups.field.quorum"), select, select.id), n, fieldHint(t("groups.field.quorum_hint")));
  return { select, n, wrap };
}

export function radiusRow() {
  const input = field("range", {
    id: "fp-group-radius", min: "25", max: "2000", step: "25", value: DEFAULT_RADIUS,
  });
  const out = document.createElement("output");
  out.htmlFor = input.id;
  out.textContent = input.value;
  const label = document.createElement("label");
  label.htmlFor = input.id;
  label.textContent = t("groups.field.radius");
  const wrap = document.createElement("div");
  wrap.className = "fp-dialog-field";
  wrap.append(label, input, out, fieldHint(t("groups.field.radius_hint")));
  return { input, out, wrap };
}

// honesty.PRESENCE_STALE, verbatim: a stale tag is not a tag left behind.
export function staleRow() {
  const input = field("number", { id: "fp-group-stale", min: "10", max: "1440", value: DEFAULT_STALE });
  const wrap = document.createElement("div");
  wrap.append(labeled(t("groups.field.stale"), input, input.id), fieldHint(t("groups.field.stale_hint")));
  return { input, wrap };
}

export function membersFieldset() {
  const fieldset = document.createElement("fieldset");
  fieldset.id = "fp-group-members";
  const legend = document.createElement("legend");
  legend.textContent = t("groups.field.members");
  fieldset.appendChild(legend);
  return { fieldset, legend };
}
