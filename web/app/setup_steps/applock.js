/*
 * Onboarding step 7 — App lock (optional).
 *
 * Purpose    : Set a first PIN, with the sentence that says what the lock does
 *              not do right next to the fields (specs/onboarding.md § 4 row 7).
 * Inputs     : ctx.postJson / ctx.state, from the Wizard.
 * Outputs    : POST /api/settings/pin, whether triggered by the Set PIN
 *              button or by pressing Next with both fields filled and
 *              matching (`onNext`, called by Wizard.next() — E13 blind-cap
 *              S2: Next used to silently discard a typed PIN because only
 *              the Set PIN button ever called the API).
 * Constraints: Skip is a true no-op: no PIN, lock stays off, exactly as if the
 *              Settings dialog had never been opened. The request shape is
 *              settings.js's first-time set, `new_pin` alone — the server's
 *              same-origin branch covers a first PIN, so there is no
 *              `current_pin` to send. Rows use `.fp-dialog-field` (the same
 *              wrapper the group/device dialogs use), not `.setting-row`:
 *              that row's `justify-content: space-between` pushed the input
 *              to the far right of the unconstrained wizard container and off
 *              the 1280px viewport (visual gate W4 F2). `onNext` returning
 *              `false` is how a step vetoes the transition (wizard.js); both
 *              fields empty is the optional-step case and must still advance.
 *              Feedback (mismatch, PIN set, an error) renders into a local
 *              `.modal-note` status line, not `ctx.showAlert`: `#alert` lives
 *              inside `#app-shell`, which is hidden for the whole time the
 *              wizard is open (setup_route.js), so an alert call here was
 *              never actually visible — the same reason
 *              `_notifications_telegram.js`/`_notifications_whatsapp.js` keep
 *              their own status line instead of the shared alert bar.
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

/**
 * POST the two fields as a new PIN if they match; render the inline mismatch
 * error and return false otherwise. Shared by the Set PIN button and Next so
 * both paths set the PIN through the exact same call.
 */
async function submitPin(ctx) {
  const first = els.pin.value.trim();
  const second = els.confirm.value.trim();
  els.status.textContent = "";
  if (first !== second) {
    els.status.textContent = t("setup.applock.mismatch");
    return false;
  }
  await ctx.postJson("/api/settings/pin", { new_pin: first });
  els.pin.value = "";
  els.confirm.value = "";
  return true;
}

async function setPin(ctx) {
  const first = els.pin.value.trim();
  const second = els.confirm.value.trim();
  if (!first && !second) return;
  try {
    if (await submitPin(ctx)) els.status.textContent = t("setup.applock.set_ok");
  } catch (err) {
    els.status.textContent = err.message;
  }
}

/**
 * Wizard.next() hook: both fields empty is the optional step doing nothing
 * (advance as today); both filled and matching sets the PIN before advancing;
 * a mismatch shows the inline error and vetoes the transition (return false).
 */
async function onNext(ctx) {
  const first = els.pin.value.trim();
  const second = els.confirm.value.trim();
  if (!first && !second) return;
  try {
    return await submitPin(ctx);
  } catch (err) {
    els.status.textContent = err.message;
    return false;
  }
}

export default {
  id: "applock",
  canSkip: true,
  onNext,
  render(container, ctx) {
    container.textContent = "";
    const heading = document.createElement("h2");
    heading.textContent = t("setup.applock.title");

    const pin = pinInput("fp-setup-pin");
    const confirm = pinInput("fp-setup-pin-confirm");

    const note = document.createElement("p");
    note.className = "fp-wizard-footnote";
    note.textContent = (ctx.state.config && ctx.state.config.notices.lock_not_encryption) || "";

    // Local status line: #alert is inside #app-shell, hidden for the whole
    // time the wizard is open, so it cannot carry this step's feedback.
    const status = document.createElement("p");
    status.id = "fp-setup-pin-status";
    status.className = "modal-note";
    status.setAttribute("aria-live", "polite");

    const submit = document.createElement("button");
    submit.type = "button";
    submit.className = "btn";
    submit.textContent = t("setup.applock.set");
    submit.addEventListener("click", () => setPin(ctx));

    els = { pin, confirm, status };
    container.append(
      heading,
      labelFor(pin, t("setup.applock.pin")),
      labelFor(confirm, t("setup.applock.pin_confirm")),
      note,
      submit,
      status
    );
  },
};
