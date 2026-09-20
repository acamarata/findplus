/*
 * Focus trap for the two custom `.modal` dialogs.
 *
 * Purpose    : #device-modal and #settings-modal are plain divs, so unlike a
 *              native <dialog> they neither hold focus nor close on Escape.
 *              This gives them both, in one place rather than once per dialog.
 * Inputs     : The dialog element, and an onClose callback the Escape key and
 *              the last-focus restore run through.
 * Outputs    : A release() function that removes the listener and returns
 *              focus to whatever opened the dialog.
 * Constraints: #fp-add-rule-dialog is a native <dialog> shown with
 *              showModal(); it already traps focus and closes on Escape, and
 *              must NOT be passed here.
 */
"use strict";

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** Every focusable descendant that is actually rendered. */
function focusable(dialogEl) {
  return [...dialogEl.querySelectorAll(FOCUSABLE)].filter(
    (el) => !el.disabled && !el.hidden && el.offsetParent !== null
  );
}

/**
 * Trap keyboard focus inside `dialogEl` until the returned release() is called.
 *
 * Focus moves to the first focusable element, Tab and Shift+Tab cycle within
 * the dialog, and Escape calls `onClose`. release() restores focus to the
 * element that was active when the trap was installed, which is the button the
 * user pressed to open the dialog.
 */
export function trapFocus(dialogEl, onClose) {
  const previous = document.activeElement;
  const first = focusable(dialogEl)[0];
  if (first) first.focus();

  function onKeydown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      if (typeof onClose === "function") onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const items = focusable(dialogEl);
    if (items.length === 0) return;
    const edge = event.shiftKey ? items[0] : items[items.length - 1];
    if (document.activeElement !== edge) return;
    event.preventDefault();
    (event.shiftKey ? items[items.length - 1] : items[0]).focus();
  }

  dialogEl.addEventListener("keydown", onKeydown);

  return {
    release() {
      dialogEl.removeEventListener("keydown", onKeydown);
      if (previous && typeof previous.focus === "function") previous.focus();
    },
  };
}
