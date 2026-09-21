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

export async function loadIconSprite() {
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
