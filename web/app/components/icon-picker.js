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
 *              built with createElement/setAttribute, never raw markup.
 */
"use strict";

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

function groupSection(group, names) {
  const section = document.createElement("section");
  section.dataset.group = group;
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
function otherSection(letterInput) {
  const section = document.createElement("section");
  section.dataset.group = "other";
  const grid = document.createElement("div");
  grid.className = "fp-icon-grid";

  const letterBtn = swatch("letter");
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

export function createIconPicker(host, { value, onChange, letterLabel = "Letter" } = {}) {
  const root = document.createElement("div");
  root.className = "fp-icon-picker";
  for (const [group, names] of groupSymbols(readSpriteSymbols())) {
    root.appendChild(groupSection(group, names));
  }
  const letterInput = createLetterInput(letterLabel);
  root.appendChild(otherSection(letterInput));
  host.appendChild(root);

  // "letter:X" pins a character the user chose; the swatch for it is the bare
  // "letter" button, so the pressed state is computed from that base id.
  let current = value || "letter";

  function applyPressedState(id) {
    const base = id.startsWith("letter:") ? "letter" : id;
    root.querySelectorAll(".fp-icon-swatch").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.dataset.iconId === base));
    });
    if (id.startsWith("letter:")) {
      letterInput.value = id.slice(7);
      letterInput.hidden = false;
    }
  }

  function emit(id) {
    current = id;
    applyPressedState(id);
    if (onChange) onChange(id);
  }

  function onSwatchClick(btn) {
    const id = btn.dataset.iconId;
    if (id === "letter") {
      // Bare "letter" is already a complete, valid value (the 0007 default),
      // so the click itself must emit -- typing a character afterward just
      // narrows it to "letter:X" via the input listener below.
      emit("letter");
      letterInput.hidden = false;
      letterInput.focus();
      return;
    }
    letterInput.hidden = true;
    emit(id);
  }

  root.querySelectorAll(".fp-icon-swatch").forEach((btn) => {
    btn.addEventListener("click", () => onSwatchClick(btn));
  });

  letterInput.addEventListener("input", () => {
    const char = letterInput.value.trim();
    if (/^[A-Za-z0-9]$/.test(char)) emit(`letter:${char.toUpperCase()}`);
    else if (char === "") emit("letter");
  });

  applyPressedState(current);

  return {
    setValue(id) {
      current = id;
      applyPressedState(id);
    },
    getValue() {
      return current;
    },
    destroy() {
      host.innerHTML = "";
    },
  };
}
