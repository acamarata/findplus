/*
 * Onboarding step 7 — App lock (optional).
 *
 * Purpose    : Set a first PIN, with the sentence that says what the lock does
 *              not do right next to the fields (specs/onboarding.md § 4 row 7).
 * Inputs     : ctx.postJson / ctx.state / ctx.showAlert, from the Wizard.
 * Outputs    : POST /api/settings/pin, and only when both fields match.
 * Constraints: Skip is a true no-op: no PIN, lock stays off, exactly as if the
 *              Settings dialog had never been opened. The request shape is
 *              settings.js's first-time set, `new_pin` alone — the server's
 *              same-origin branch covers a first PIN, so there is no
 *              `current_pin` to send. Rows use `.fp-dialog-field` (the same
 *              wrapper the group/device dialogs use), not `.setting-row`:
 *              that row's `justify-content: space-between` pushed the input
 *              to the far right of the unconstrained wizard container and off
 *              the 1280px viewport (visual gate W4 F2).
 */
"use strict";

import { t } from "../i18n.js";

/** The live step's fields, replaced on every render. */
let els = null;

/** A real `<label for>` beside its input, used for both PIN fields — the same
 * wrapper devices_dialog.js's/groups_dialog_dom.js's own `labeled()` builds. */
function labelFor(input, text) {
  const label = document.createElement("label");
  label.htmlFor = input.id;
  label.textContent = text;
  const wrap = document.createElement("div");
  wrap.className = "fp-dialog-field";
  wrap.append(label, input);
  return wrap;
}

function pinInput(id) {
  const input = document.createElement("input");
  input.type = "password";
  input.id = id;
  input.inputMode = "numeric";
  input.autocomplete = "new-password";
  return input;
}

async function setPin(ctx) {
  const first = els.pin.value.trim();
  const second = els.confirm.value.trim();
  if (!first && !second) return;
  if (first !== second) {
    ctx.showAlert(t("setup.applock.mismatch"), "warn");
    return;
  }
  try {
    await ctx.postJson("/api/settings/pin", { new_pin: first });
    els.pin.value = "";
    els.confirm.value = "";
    ctx.showAlert(t("setup.applock.set_ok"), "warn");
  } catch (err) {
    ctx.showAlert(err.message, "err");
  }
}

export default {
  id: "applock",
  canSkip: true,
  render(container, ctx) {
    container.textContent = "";
    const heading = document.createElement("h2");
    heading.textContent = t("setup.applock.title");

    const pin = pinInput("fp-setup-pin");
    const confirm = pinInput("fp-setup-pin-confirm");

    const note = document.createElement("p");
    note.className = "fp-wizard-footnote";
    note.textContent = (ctx.state.config && ctx.state.config.notices.lock_not_encryption) || "";

    const submit = document.createElement("button");
    submit.type = "button";
    submit.className = "btn";
    submit.textContent = t("setup.applock.set");
    submit.addEventListener("click", () => setPin(ctx));

    els = { pin, confirm };
    container.append(
      heading,
      labelFor(pin, t("setup.applock.pin")),
      labelFor(confirm, t("setup.applock.pin_confirm")),
      note,
      submit
    );
  },
};
