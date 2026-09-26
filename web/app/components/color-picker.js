/*
 * Colour picker: the 12 palette swatches plus a custom hex input.
 *
 * Purpose    : Let a dialog pick the colour a device or group badge is drawn
 *              in, always as the lowercase "#rrggbb" string labels.py's
 *              validate_color accepts.
 * Inputs     : `host` to mount into, the current `value`, an `onChange`
 *              callback, and `customLabel` — the accessible name for the
 *              native colour input, passed in so no English is baked in here.
 * Outputs    : onChange(hex) on every selection, and a handle of
 *              { setValue(hex), getValue(), destroy() }.
 * Constraints: The palette below is a display-only copy of labels.py's
 *              DEVICE_PALETTE — same 12 values in the same order, but nothing
 *              hashes against it here, so it never has to match byte for byte.
 *              Every element is built with createElement/setAttribute, never
 *              raw markup; onChange is the one notification path.
 */
"use strict";

const DEVICE_PALETTE = [
  "#4f8cf7",
  "#e7663f",
  "#37c67a",
  "#c77ae6",
  "#e7b53f",
  "#3fc9d6",
  "#e64f7a",
  "#8fb43f",
  "#f2994a",
  "#9b6bd6",
  "#4fd6a8",
  "#d65f5f",
];

function paletteSwatch(hex) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "fp-color-swatch";
  btn.dataset.color = hex;
  btn.style.background = hex;
  btn.setAttribute("aria-pressed", "false");
  btn.setAttribute("aria-label", hex);
  return btn;
}

function customInput(customLabel) {
  const input = document.createElement("input");
  input.type = "color";
  // N28: fp-color-custom--round (places-events.css) clips the native
  // <input type="color"> swatch into a circle to match the 12 palette
  // swatches beside it, which were already round -- this one alone painted
  // as a native rectangle.
  input.className = "fp-color-custom fp-color-custom--round";
  input.setAttribute("aria-label", customLabel);
  return input;
}
import { t } from "../i18n.js";

export function createColorPicker(host, { value, onChange, customLabel = t("field.customColor") } = {}) {
  const root = document.createElement("div");
  root.className = "fp-color-picker";
  for (const hex of DEVICE_PALETTE) root.appendChild(paletteSwatch(hex));
  const custom = customInput(customLabel);
  root.appendChild(custom);
  host.appendChild(root);

  let current = (value || DEVICE_PALETTE[0]).toLowerCase();

  function applyPressedState(hex) {
    root.querySelectorAll(".fp-color-swatch").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.dataset.color === hex));
    });
    // Keep the native input showing the selection too, whichever way it was
    // made, so the two controls never disagree about the current colour.
    custom.value = hex;
  }

  function emit(hex) {
    current = hex;
    applyPressedState(hex);
    if (onChange) onChange(hex);
  }

  root.querySelectorAll(".fp-color-swatch").forEach((btn) => {
    btn.addEventListener("click", () => emit(btn.dataset.color));
  });

  // <input type="color"> already yields "#rrggbb"; the lowercasing is what
  // keeps the emitted value matching labels.py's ^#[0-9a-f]{6}$ regardless.
  custom.addEventListener("input", () => emit(custom.value.toLowerCase()));

  applyPressedState(current);

  return {
    setValue(hex) {
      current = (hex || DEVICE_PALETTE[0]).toLowerCase();
      applyPressedState(current);
    },
    getValue() {
      return current;
    },
    destroy() {
      host.innerHTML = "";
    },
  };
}
