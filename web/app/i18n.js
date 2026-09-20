/*
 * Find+ dashboard — i18n runtime.
 *
 * Purpose    : One place every user-visible string is read from, so a second
 *              locale can replace web/locales/en.json 1:1 without touching any
 *              other file. English is the only catalog that ships in 1.1.
 * Inputs     : /static/locales/<locale>.json, fetched once per locale; the
 *              bundled CATALOG_EN as the fallback when that fetch fails or the
 *              loaded catalog is missing a key.
 * Outputs    : loadCatalog / t / plural / setLocale / applyStaticI18n.
 * Constraints:
 *   - Plain ES module, no build step and no Node dependency (ADR-P1-07).
 *   - t() and plural() are synchronous and read an already-loaded catalog:
 *     every caller sits downstream of `await loadCatalog()` in main.js's boot.
 *   - A missing key returns the key itself. Never throws, never renders empty —
 *     a translator gap has to be visible, not silent.
 */
"use strict";

import { CATALOG_EN } from "./catalog-en.js";

/** The catalog in force. Replaced wholesale by loadCatalog(), never mutated. */
let catalog = CATALOG_EN;
let currentLocale = "en";

/**
 * Walk a dot-path through a catalog object.
 *
 * Returns undefined for a missing key at any depth, and for a key that resolves
 * to something other than a string (a pluralised entry's parent object, say),
 * so the caller can fall through to CATALOG_EN.
 */
function resolve(source, key) {
  let node = source;
  for (const part of key.split(".")) {
    if (node === null || typeof node !== "object" || !(part in node)) return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

/** Replace every literal `{name}` in `text` with `vars[name]`. */
function substitute(text, vars) {
  if (!vars) return text;
  let out = text;
  for (const name of Object.keys(vars)) {
    out = out.split(`{${name}}`).join(String(vars[name]));
  }
  return out;
}

/**
 * Load `locale`'s catalog into module scope.
 *
 * On any fetch or parse failure the bundled English catalog stays in force, so
 * a dashboard served without its locales directory still renders real text.
 */
export async function loadCatalog(locale = "en") {
  currentLocale = locale;
  try {
    const res = await fetch(`/static/locales/${locale}.json`, {
      headers: { Accept: "application/json" },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const parsed = await res.json();
    if (!parsed || typeof parsed !== "object") throw new Error("not an object");
    catalog = parsed;
  } catch (_) {
    catalog = CATALOG_EN;
  }
}

/**
 * The string at dot-path `key`, with `{name}` placeholders filled from `vars`.
 *
 * Falls through to the bundled English catalog key by key, not only when the
 * whole fetch failed: a partial translation shows English for what it is
 * missing rather than a raw key.
 */
export function t(key, vars) {
  const text = resolve(catalog, key) ?? resolve(CATALOG_EN, key);
  if (text === undefined) return key;
  return substitute(text, vars);
}

/**
 * The `.one` or `.other` form of a pluralised entry.
 *
 * English-only rule for 1.1: n === 1 picks `.one`, everything else (including 0)
 * picks `.other`. A locale needing more categories is a later problem for this
 * function, not for its callers.
 */
export function plural(key, n, vars) {
  return t(`${key}.${n === 1 ? "one" : "other"}`, vars);
}

/**
 * Render every element carrying `data-i18n` / `data-i18n-attr` from the catalog.
 *
 * T2 gives this its DOM walk; the export exists from this ticket so setLocale()
 * and main.js's boot sequence can be written against the final signature.
 */
export function applyStaticI18n() {
  /* implemented in P2-E9-W2-S1-T2 */
}

/**
 * Switch locale and re-render the static markup.
 *
 * Stores nothing: 1.1 has no locale picker and only ever passes "en". The
 * signature exists so adding one later changes no caller.
 */
export async function setLocale(locale) {
  await loadCatalog(locale);
  applyStaticI18n();
}

/** The locale loadCatalog() was last called with. */
export function getLocale() {
  return currentLocale;
}
