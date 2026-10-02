/*
 * A sign-in sheet: a native <dialog> that holds focus and cancels on Escape.
 *
 * Purpose    : Open and close the Apple sign-in sheet the same way wherever the
 *              card lives: in the wizard, or inside the Settings dialog, whose
 *              own focus trap (components/dialog-trap.js) also listens for
 *              Escape and Tab. The sheet keeps those keys to itself, so Escape
 *              cancels the sign-in instead of closing Settings behind it.
 * Inputs     : The <dialog> element; a cancel callback.
 * Outputs    : openSheet(), closeSheet(), wireSheetKeys().
 * Constraints: showModal() when the browser has it (focus stays inside and
 *              the page behind is inert); a plain `open` attribute otherwise.
 */
"use strict";

export function openSheet(sheet) {
  if (sheet.open) return;
  if (typeof sheet.showModal === "function") {
    try {
      sheet.showModal();
      return;
    } catch (_err) {
      // Not connected or already open somewhere: fall through.
    }
  }
  sheet.setAttribute("open", "");
}

export function closeSheet(sheet) {
  if (!sheet.open) return;
  if (typeof sheet.close === "function") sheet.close();
  else sheet.removeAttribute("open");
}

/** Escape cancels; Escape and Tab never reach a trap around the sheet. */
export function wireSheetKeys(sheet, onCancel) {
  sheet.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onCancel();
    } else if (event.key === "Tab") {
      event.stopPropagation();
    }
  });
  // The browser's own cancel (Escape with no keydown seen, e.g. a close request).
  sheet.addEventListener("cancel", (event) => {
    event.preventDefault();
    onCancel();
  });
}
