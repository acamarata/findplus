/*
 * Put the bundled Lucide icon sprite in the document once, at boot.
 *
 * Purpose    : Split out of main.js (loop2 B2, PRI rule 7's 300-line file cap
 *              -- main.js was at 301 after E13's alerts.js boot-import fix).
 * Inputs     : /static/icons.svg, served by the daemon.
 * Outputs    : Prepends the parsed <svg> root to document.body once.
 * Constraints: `<use href="#lucide-dog">` only resolves against a symbol in
 *              the SAME document, so the sprite has to be inlined rather than
 *              referenced as an external file. Never innerHTML: the parsed
 *              SVG element is prepended as a node. A missing or malformed
 *              sprite must never inject anything into the page -- a 404
 *              still resolves the fetch, and a bad parse still returns a
 *              document, so both are checked explicitly rather than relying
 *              on a throw.
 */
"use strict";

/** The one load in flight or done, so a second caller never adds a second sprite. */
let loading = null;

/**
 * Load the sprite once per document.
 *
 * Two callers now: main.js at dashboard boot, and the sign-in cards
 * (signin/cards.js), which a first-run setup wizard renders before the
 * dashboard has ever booted. A second copy would duplicate every symbol id.
 * A failed load is forgotten so a later caller can try again.
 */
export function loadIconSprite() {
  if (!loading) {
    loading = fetchSprite().catch((err) => {
      loading = null;
      throw err;
    });
  }
  return loading;
}

async function fetchSprite() {
  if (document.getElementById("lucide-user")) return;
  const res = await fetch("/static/icons.svg");
  if (!res.ok) return;
  const text = await res.text();
  const doc = new DOMParser().parseFromString(text, "image/svg+xml");
  if (doc.querySelector("parsererror") || doc.documentElement.nodeName !== "svg") {
    console.warn("icon sprite failed to parse");
    return;
  }
  document.body.prepend(doc.documentElement);
}
