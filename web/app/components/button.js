/*
 * The 1.3 button system: one helper that builds every action button.
 *
 * Purpose    : Give Add place, Edit, Delete, Poll now, Settings and the rest
 *              one look (web/components.css `.fp-btn`) and one construction
 *              path, so a later change to the look is one stylesheet edit.
 * Inputs     : button({ label, icon, variant, size, title, onClick, iconOnly,
 *                id, attrs })
 *                label    visible text (string). With `iconOnly` it becomes
 *                         the aria-label and tooltip instead.
 *                icon     sprite name without the "lucide-" prefix, e.g.
 *                         "plus" (symbols live in web/icons.svg, group "ui").
 *                variant  "primary" | "secondary" (default) | "ghost" | "danger".
 *                size     "sm" or omitted.
 *                title    tooltip; defaults to nothing for labelled buttons.
 *                onClick  click handler.
 *                labelKey, titleKey  catalog keys for static chrome built before
 *                         the catalog loads: i18n.js applyStaticI18n() then
 *                         fills the label span / title (label stays the fallback).
 *                id, attrs  optional id and a {name: value} map of attributes.
 * Outputs    : A `<button type="button" class="fp-btn ...">` element. The icon
 *              is an aria-hidden inline SVG `<use>`; the text (or aria-label
 *              when icon-only) names the button.
 * Constraints: Nodes only, never an innerHTML template. Delete buttons use
 *              variant "danger" and the caller still confirms.
 */
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const VARIANTS = ["primary", "secondary", "ghost", "danger"];

/** An aria-hidden sprite icon; the sprite is loaded once at boot (icon_sprite.js). */
export function buttonIcon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.setAttribute("class", "fp-btn-icon");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#lucide-${name}`);
  svg.appendChild(use);
  return svg;
}

/** Build one `.fp-btn`. See the header for the options. */
export function button({ label = "", icon, variant = "secondary", size, title, onClick, iconOnly = false, id, attrs, labelKey, titleKey } = {}) {
  const btn = document.createElement("button");
  btn.type = "button";
  const kind = VARIANTS.includes(variant) ? variant : "secondary";
  btn.className = `fp-btn fp-btn--${kind}`;
  if (size === "sm") btn.classList.add("fp-btn--sm");
  if (id) btn.id = id;
  if (icon) btn.appendChild(buttonIcon(icon));
  if (iconOnly) {
    btn.classList.add("fp-btn--icon");
    btn.setAttribute("aria-label", label);
    btn.title = title || label;
  } else {
    const text = document.createElement("span");
    text.className = "fp-btn-label";
    text.textContent = label;
    if (labelKey) text.dataset.i18n = labelKey;
    btn.appendChild(text);
    if (title) btn.title = title;
  }
  if (titleKey) btn.dataset.i18nAttr = `title:${titleKey}`;
  Object.entries(attrs || {}).forEach(([name, value]) => btn.setAttribute(name, value));
  if (onClick) btn.addEventListener("click", onClick);
  return btn;
}

/** Restyle an existing static button (index.html markup) as a `.fp-btn`, keeping its id and listeners. */
export function styleAsButton(el, { icon, variant = "secondary", size } = {}) {
  el.classList.remove("btn", "btn-secondary", "btn-tiny", "btn-danger");
  el.classList.add("fp-btn", `fp-btn--${VARIANTS.includes(variant) ? variant : "secondary"}`);
  if (size === "sm") el.classList.add("fp-btn--sm");
  if (!el.querySelector(".fp-btn-label")) {
    const label = document.createElement("span");
    label.className = "fp-btn-label";
    label.textContent = el.textContent;
    el.replaceChildren(label);
  }
  if (icon && !el.querySelector(".fp-btn-icon")) el.prepend(buttonIcon(icon));
  return el;
}

/** Set a button's visible text without dropping its icon (textContent would). */
export function setButtonLabel(btn, text) {
  const label = btn.querySelector(".fp-btn-label");
  if (label) label.textContent = text;
  else btn.textContent = text;
}
