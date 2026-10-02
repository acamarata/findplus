/*
 * Wizard drafts: keep what someone typed when they step Back or Skip.
 *
 * Purpose    : Every step is re-rendered from scratch on each visit, so a PIN,
 *              a group name or a Telegram token typed before pressing Back was
 *              gone on return. This remembers the typed values of a step's
 *              fields and puts them back after the step has rendered.
 * Inputs     : A Map owned by one Wizard, a step id and the step's container.
 * Outputs    : saveDraft() copies values in; restoreDraft() writes them back
 *              into fields that are still empty; the Map is cleared when the
 *              wizard is torn down (closeSetup), so nothing outlives it.
 * Constraints: Memory only, never storage. Only fields with an id are kept
 *              (the id is the key). Checkboxes are server state and are left
 *              alone. A sign-in card's password is never kept: it is cleared on
 *              purpose after a connect attempt and must not come back.
 */
"use strict";

const SKIP_TYPES = new Set(["checkbox", "radio", "button", "submit", "file", "hidden"]);

function keptFields(root) {
  return [...root.querySelectorAll("input[id], textarea[id], select[id]")].filter(
    (el) => !SKIP_TYPES.has(el.type) && !(el.type === "password" && el.closest(".fp-signin-card"))
  );
}

/** Remember every non-empty field of the step being left. */
export function saveDraft(drafts, stepId, root) {
  const values = {};
  keptFields(root).forEach((el) => {
    if (el.value) values[el.id] = el.value;
  });
  if (Object.keys(values).length) drafts.set(stepId, values);
  else drafts.delete(stepId);
}

/** Put remembered values back into fields that are empty right now. */
export function restoreDraft(drafts, stepId, root) {
  const values = drafts.get(stepId);
  if (!values) return;
  keptFields(root).forEach((el) => {
    if (!el.value && values[el.id] !== undefined) el.value = values[el.id];
  });
}
