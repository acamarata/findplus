/*
 * Wizard close control: a 32 px icon button (an X) in the card's top-right corner.
 *
 * Purpose    : "Skip setup" / "Close setup" used to be a 12 px underlined link
 *              that was easy to miss and hard to hit (1.3, U38). It is now an
 *              icon button; the words live in its aria-label and tooltip.
 * Inputs     : `label` (already translated) and `onClick`.
 * Outputs    : A <button type="button"> with the X drawn as inline SVG.
 * Constraints: Drawn inline (two strokes), not from the icon sprite, so it
 *              exists before the sprite has loaded and needs no new symbol.
 *              The id and `fp-wizard-skip` class stay as they were so existing
 *              selectors and the grid placement in setup.css still match.
 */
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";

/** The X glyph: two diagonal strokes, decorative. */
function crossIcon() {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const d of ["M6 6l12 12", "M18 6L6 18"]) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.appendChild(path);
  }
  return svg;
}

/** Build the close button. */
export function closeButton(label, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "fp-wizard-skip-all";
  btn.className = "fp-wizard-skip fp-wizard-close";
  btn.setAttribute("aria-label", label);
  btn.title = label;
  btn.appendChild(crossIcon());
  btn.addEventListener("click", onClick);
  return btn;
}
