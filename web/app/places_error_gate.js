/*
 * Places tab: turn "Add place" off, with a reason, while the list failed to load.
 *
 * Purpose    : U29. When the places list cannot be loaded, adding a place would
 *              hide the problem (and the new place would never show). The Add
 *              button is disabled and a visible one-line reason sits beside
 *              it until the list loads again (Retry in the error pane).
 * Inputs     : The list element places_list.js renders into, and the Add button.
 * Outputs    : `disabled` + `aria-describedby` on the button and a
 *              `#fp-places-add-reason` hint; both cleared when the list is back.
 * Constraints: places_list.js renders the error with pane_error.js (marked
 *              `data-pane-error`); this watches for that marker instead of
 *              reaching into the list code.
 */
"use strict";

import { t } from "./i18n.js";

/** Watch `listEl` and keep `addBtn` in step with whether the list shows its error pane. */
export function gateAddOnLoadError(listEl, addBtn) {
  if (!listEl || !addBtn || typeof MutationObserver === "undefined") return null;
  const reason = document.createElement("p");
  reason.id = "fp-places-add-reason";
  reason.className = "fp-field-hint";
  reason.hidden = true;
  reason.textContent = t("places.addDisabledLoadFailed");
  addBtn.insertAdjacentElement("afterend", reason);

  function sync() {
    const failed = Boolean(listEl.querySelector("[data-pane-error]"));
    addBtn.disabled = failed;
    reason.hidden = !failed;
    if (failed) addBtn.setAttribute("aria-describedby", reason.id);
    else addBtn.removeAttribute("aria-describedby");
  }
  const observer = new MutationObserver(sync);
  observer.observe(listEl, { childList: true });
  sync();
  return observer;
}
