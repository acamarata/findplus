/*
 * Place kind: Home, School, Work, Family, Shop, Other.
 *
 * Purpose    : Home is special (left-behind alerts are off there and the day
 *              summary starts "Overnight at Home"), so every place has a kind.
 *              The dialog guesses it from the name ("Grandma's" is Family) and
 *              the owner confirms it.
 * Inputs     : A place name; the kind select built here.
 * Outputs    : guessKind(name), buildKindField(), syncKindHint().
 * Constraints: guessKind() mirrors findplus/places/kinds.py word for word (a test
 *              compares them on a list of names). A kind the owner picked is never
 *              overwritten by a later guess.
 */
"use strict";

import { t } from "./i18n.js";

export const KINDS = ["home", "school", "work", "family", "shop", "other"];

const WORDS = {
  // Family first: "Grandma's House" is Grandma's, not a home (same order as places/kinds.py).
  family: ["grandma", "grandpa", "granny", "grandad", "granddad", "nana", "nan", "papa", "aunt", "auntie", "uncle", "cousin", "nanny", "jaddah", "jaddi"],
  home: ["home", "house", "flat", "apartment"],
  school: ["school", "academy", "college", "university", "uni", "kindergarten", "nursery", "preschool", "madrasa", "madrassa", "daycare"],
  work: ["work", "office", "job", "workplace"],
  shop: ["shop", "store", "market", "supermarket", "mall", "grocery"],
};

/** The kind a place name suggests, else "other". */
export function guessKind(name) {
  const words = String(name || "").toLowerCase().replace(/['’]s\b/g, "").split(/[^a-z]+/);
  for (const [kind, vocab] of Object.entries(WORDS)) {
    if (words.some((w) => vocab.includes(w))) return kind;
  }
  return "other";
}

/**
 * The hint under the select: why Home matters, or that the kind was guessed.
 * "Guessed from the name" is only said once a name was typed and the guess found a kind
 * (UAT 11: it used to show on an empty dialog, before there was a name to guess from).
 */
export function syncKindHint(field, guessed = false) {
  const home = field.select.value === "home";
  field.hint.textContent = home ? t("places.kind.homeHint") : guessed ? t("places.kind.hint") : "";
  field.hint.hidden = !field.hint.textContent;
}

/** True when `name` is typed and the guess picked a real kind, so the note is honest. */
export function guessedFrom(name) {
  return String(name || "").trim() !== "" && guessKind(name) !== "other";
}

/** `{wrap, select, hint}`; `select.dataset.touched` becomes "1" once the owner picks. */
export function buildKindField() {
  const select = document.createElement("select");
  select.id = "fp-place-kind";
  KINDS.forEach((kind) => {
    const opt = document.createElement("option");
    opt.value = kind;
    opt.textContent = t(`places.kind.${kind}`);
    select.appendChild(opt);
  });
  const label = document.createElement("label");
  label.htmlFor = select.id;
  label.textContent = t("places.kind.label");
  const hint = document.createElement("p");
  hint.className = "fp-field-hint";
  hint.id = "fp-place-kind-hint";
  select.setAttribute("aria-describedby", hint.id);
  const row = document.createElement("div");
  row.className = "fp-dialog-field";
  row.append(label, select);
  const wrap = document.createElement("div");
  wrap.append(row, hint);
  const field = { wrap, select, hint };
  select.addEventListener("change", () => { select.dataset.touched = "1"; syncKindHint(field); });
  field.hint.hidden = true;
  return field;
}
