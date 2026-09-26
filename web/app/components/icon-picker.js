/*
 * Icon picker: the grouped Lucide swatch grid plus the letter and none choices.
 *
 * Purpose    : Let a dialog pick one icon id for a device or a group, in the
 *              grammar labels.py validates: "lucide:<name>", "letter:<CHAR>",
 *              bare "letter" (the character follows the name) or "none".
 * Inputs     : `host` to mount into, the current `value`, an `onChange`
 *              callback, and `letterLabel` — the accessible name for the
 *              one-character input, passed in so no English is baked in here.
 * Outputs    : onChange(id) on every selection, and a handle of
 *              { setValue(id), getValue(), destroy() }.
 * Constraints: Reads the <symbol> elements main.js already put in the page at
 *              boot. No fetch, no dependency on GET /api/icons (that route
 *              serves the CLI and tests), no CustomEvent — onChange is the one
 *              notification path, as places_dialog.js does it. Every element is
 *              built with createElement/setAttribute, never raw markup. The
 *              one exception to "no fetch": the "Your icons" section
 *              (custom-icons.js) is per-installation and cannot live in the
 *              static sprite, so it fetches its own list independently.
 * N28: each `<section data-group="…">` keeps its own grid (pinned by
 * test_icon_picker_renders_grouped_sections) rather than one continuous
 * grid, so a category heading is what turns "rows of 9, 8, 9, 9, 4…" from a
 * layout bug into a deliberate boundary.
 */
"use strict";

import { t } from "../i18n.js";
import { createCustomIconsSection } from "./custom-icons.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const SPRITE_SELECTOR = '#fp-icon-sprite symbol[id^="lucide-"]';

/** The sprite is static once loaded, so this is a fresh read per dialog open. */
export function readSpriteSymbols() {
  return Array.from(document.querySelectorAll(SPRITE_SELECTOR));
}

/** [group, names[]] pairs in the sprite's own order — no re-sorting. */
function groupSymbols(symbols) {
  const groups = new Map();
  for (const symbol of symbols) {
    const group = symbol.dataset.group || "other";
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(symbol.id.slice(7));
  }
  return Array.from(groups.entries());
}

function swatch(iconId, accessibleName) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "fp-icon-swatch";
  btn.dataset.iconId = iconId;
  btn.setAttribute("aria-pressed", "false");
  if (accessibleName) btn.setAttribute("aria-label", accessibleName);
  return btn;
}

function iconSwatch(name) {
  // The icon id doubles as the accessible name: an icon-only button needs one
  // (specs/layout-i18n-a11y.md), and an id is not prose that needs translating.
  const btn = swatch(`lucide:${name}`, name.replace(/-/g, " "));
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("width", "20");
  svg.setAttribute("height", "20");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#lucide-${name}`);
  svg.appendChild(use);
  btn.appendChild(svg);
  return btn;
}

const CATEGORY_KEYS = {
  people: "icons.category.people",
  pets: "icons.category.pets",
  things: "icons.category.things",
  places: "icons.category.places",
  other: "icons.category.other",
};

function categoryHeading(group) {
  const heading = document.createElement("h3");
  heading.className = "fp-icon-group-heading";
  const key = CATEGORY_KEYS[group];
  heading.textContent = key ? t(key) : group;
  return heading;
}

function groupSection(group, names) {
  const section = document.createElement("section");
  section.dataset.group = group;
  section.appendChild(categoryHeading(group));
  const grid = document.createElement("div");
  grid.className = "fp-icon-grid";
  for (const name of names) grid.appendChild(iconSwatch(name));
  section.appendChild(grid);
  return section;
}

function createLetterInput(letterLabel) {
  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = 1;
  input.className = "fp-icon-letter-input";
  input.setAttribute("aria-label", letterLabel);
  input.hidden = true;
  return input;
}

/** The letter and none swatches, plus the (hidden) one-character input. */
function otherSection(letterInput, letterLabel) {
  const section = document.createElement("section");
  section.dataset.group = "other";
  section.appendChild(categoryHeading("other"));
  const grid = document.createElement("div");
  grid.className = "fp-icon-grid";

  // "Aa" is a visual glyph, not translatable prose, but its accessible name
  // still needs to say "letter" in the caller's language -- that is what
  // letterLabel is passed in for.
  const letterBtn = swatch("letter", letterLabel);
  letterBtn.textContent = "Aa";
  grid.appendChild(letterBtn);

  const noneBtn = swatch("none", "none");
  const dot = document.createElement("span");
  dot.className = "fp-icon-none-dot";
  noneBtn.appendChild(dot);
  grid.appendChild(noneBtn);

  section.appendChild(grid);
  section.appendChild(letterInput);
  return section;
}

/** Toggle aria-pressed to match `id`, and show/hide the letter input for it. */
function applyPressedState(root, letterInput, id) {
  // "letter:X" pins a character the user chose; the swatch for it is the bare
  // "letter" button, so the pressed state is computed from that base id.
  const base = id.startsWith("letter:") ? "letter" : id;
  root.querySelectorAll(".fp-icon-swatch").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.iconId === base));
  });
  if (id.startsWith("letter:")) {
    letterInput.value = id.slice(7);
    letterInput.hidden = false;
  } else {
    letterInput.hidden = true;
  }
}

/** The one static-grid swatch click: bare "letter" emits immediately (it is
 * already a complete, valid value, the 0007 default) and reveals the input;
 * everything else hides it and emits its own id. */
function onSwatchClick(btn, letterInput, emit) {
  const id = btn.dataset.iconId;
  if (id === "letter") {
    emit("letter");
    letterInput.hidden = false;
    letterInput.focus();
    return;
  }
  letterInput.hidden = true;
  emit(id);
}

/** Wire every static-grid swatch and the letter input to `emit`. */
function wireStaticInputs(root, letterInput, emit) {
  root.querySelectorAll(".fp-icon-swatch").forEach((btn) => {
    btn.addEventListener("click", () => onSwatchClick(btn, letterInput, emit));
  });
  letterInput.addEventListener("input", () => {
    const char = letterInput.value.trim();
    if (/^[A-Za-z0-9]$/.test(char)) emit(`letter:${char.toUpperCase()}`);
    else if (char === "") emit("letter");
  });
}

/** Wire swatch clicks and the letter input, and return the picker's public handle.
 *
 * `onPressedExtra`, when given, is told about every selection (including the
 * initial one) so the "Your icons" section — mounted after this returns,
 * since its own contents arrive asynchronously — can keep its swatches'
 * aria-pressed in sync with a selection made anywhere else in the picker. */
function wireIconPicker(host, root, letterInput, initial, onChange, onPressedExtra) {
  let current = initial;

  function emit(id) {
    current = id;
    applyPressedState(root, letterInput, id);
    if (onPressedExtra) onPressedExtra(id);
    if (onChange) onChange(id);
  }

  wireStaticInputs(root, letterInput, emit);
  applyPressedState(root, letterInput, current);

  return {
    setValue(id) {
      current = id;
      applyPressedState(root, letterInput, id);
      if (onPressedExtra) onPressedExtra(id);
    },
    getValue() {
      return current;
    },
    /** Selection entry point for a swatch this module did not wire itself —
     * today, only custom-icons.js's asynchronously-rendered swatches. */
    selectExternal(id) {
      emit(id);
    },
    destroy() {
      host.innerHTML = "";
    },
  };
}

export function createIconPicker(host, { value, onChange, letterLabel = "Letter" } = {}) {
  const root = document.createElement("div");
  root.className = "fp-icon-picker";
  for (const [group, names] of groupSymbols(readSpriteSymbols())) {
    root.appendChild(groupSection(group, names));
  }
  const letterInput = createLetterInput(letterLabel);
  root.appendChild(otherSection(letterInput, letterLabel));
  host.appendChild(root);

  let customIcons = null;
  const handle = wireIconPicker(host, root, letterInput, value || "letter", onChange, (id) => {
    if (customIcons) customIcons.setPressed(id);
  });
  customIcons = createCustomIconsSection(root, {
    value: handle.getValue(),
    onSelect: (id) => handle.selectExternal(id),
  });

  return handle;
}
