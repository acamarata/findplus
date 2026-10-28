/*
 * The rule dialog's Name field fills itself in ("Sam at School") from the chosen
 * tracker or group and place, until the person types a name of their own.
 *
 * Purpose    : Name is required but nobody wants to invent one (U12). The field stays
 *              editable and stays required; this only proposes a value.
 * Inputs     : resetAutoName(isNewRule) when the dialog opens; syncAutoName({ who,
 *              place, ev }) from alerts_rule_preview.js's refreshPreview().
 * Outputs    : #fp-rule-name's value.
 * Constraints: Never touches an existing rule's name (editing) or text the person
 *              typed. Emptying the field hands the name back, but it is refilled on
 *              the next tracker/place change, never while they are still typing.
 */
"use strict";

import { $ } from "./state.js";
import { t } from "./i18n.js";

/** True while the name is still ours to fill. */
let auto = false;

/** A new rule starts auto-named; an edited rule keeps its own name. */
export function resetAutoName(isNewRule) {
  auto = Boolean(isNewRule);
}

/** Wire once: typing takes the name over; clearing it gives it back. */
export function wireAutoName() {
  $("fp-rule-name").addEventListener("input", (ev) => {
    auto = ev.target.value === "";
  });
}

/** Propose "who at place" once both are chosen. `ev` is the form event that
 *  caused the refresh, so keystrokes in the name field itself are left alone. */
export function syncAutoName({ who, place, ev }) {
  if (!auto || !who || !place) return;
  if (ev && ev.target && ev.target.id === "fp-rule-name") return;
  $("fp-rule-name").value = t("alerts.autoName", { who, place });
}
