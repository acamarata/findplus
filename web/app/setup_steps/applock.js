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
 *              A mismatch, a too-short PIN, or the server rejecting one all
 *              render beside the New PIN field (settings.js's
 *              #setting-new-pin-error pattern, UAT4 N35), not the status
 *              line below the button -- that line is reserved for the
 *              set-ok confirmation. `ctx.showAlert` is never used here:
 *              `#alert` lives inside `#app-shell`, which is hidden for the
 *              whole time the wizard is open (setup_route.js), so an alert
 *              call here was never actually visible — the same reason
 *              `_notifications_telegram.js`/`_notifications_whatsapp.js` keep
 *              their own status line instead of the shared alert bar.
 */
"use strict";

import { t } from "../i18n.js";

/** security.py's MIN_PIN_LENGTH — kept in sync by hand, same discipline
 * honesty.py's sentences already require (specs/honesty.md). Checking this
 * client-side (UAT4 N44) is a courtesy that saves a round trip; the server
 * still enforces it regardless. */
const MIN_PIN_LENGTH = 6;

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

/** The New PIN field's own error line, matching settings.js's
 * showNewPinError/#setting-new-pin-error (UAT4 N35). `message` null/empty
 * clears it.
 *
 * GP-R5-5: a mismatch is about both fields, not just New PIN -- #fp-setup-pin
 * and #fp-setup-pin-confirm both carry aria-invalid, the same twin fix as
 * settings.js's showNewPinError(). */
function setFieldError(message) {
  els.fieldError.textContent = message || "";
  els.fieldError.classList.toggle("hidden", !message);
  els.pin.setAttribute("aria-invalid", String(!!message));
  els.confirm.setAttribute("aria-invalid", String(!!message));
}

/**
 * POST the two fields as a new PIN if they match and meet the minimum
 * length; render the inline field error and return false otherwise. Shared
 * by the Set PIN button and Next so both paths set the PIN through the exact
 * same call. UAT4 N44: the length check runs before the request, the same
 * order settings.js's setPin() now checks in, so a too-short PIN never
 * reaches the server at all (no 400 in the console).
 */
async function submitPin(ctx) {
  const first = els.pin.value.trim();
  const second = els.confirm.value.trim();
  setFieldError(null);
  els.status.textContent = "";
  if (first !== second) {
    setFieldError(t("settings.pinsDoNotMatch"));
    return false;
  }
  if (first.length < MIN_PIN_LENGTH) {
    setFieldError(t("settings.pinTooShort"));
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
    setFieldError(err.message);
  }
}

/**
 * Wizard.next() hook: both fields empty is the optional step doing nothing
 * (advance as today); both filled, matching and long enough sets the PIN
 * before advancing; any rejection shows the inline field error and vetoes
 * the transition (return false) so Next never silently stays put.
 */
async function onNext(ctx) {
  const first = els.pin.value.trim();
  const second = els.confirm.value.trim();
  if (!first && !second) return;
  try {
    return await submitPin(ctx);
  } catch (err) {
    setFieldError(err.message);
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
    pin.setAttribute("aria-describedby", "fp-setup-pin-error");
    // GP-R5-5: the mismatch error is about both fields (settings.js's
    // #confirm-pin twin fix), so Confirm PIN needs the same describedby.
    confirm.setAttribute("aria-describedby", "fp-setup-pin-error");

    // UAT4 N35: mismatch/too-short/server errors render here, right after
    // the New PIN field -- settings.js's #setting-new-pin-error convention,
    // not the status line below the button.
    const fieldError = document.createElement("p");
    fieldError.id = "fp-setup-pin-error";
    fieldError.className = "fp-dialog-error hidden";

    const note = document.createElement("p");
    note.className = "fp-wizard-footnote";
    note.textContent = (ctx.state.config && ctx.state.config.notices.lock_not_encryption) || "";

    // Local status line: #alert is inside #app-shell, hidden for the whole
    // time the wizard is open, so it cannot carry this step's feedback. Now
    // carries only the set-ok confirmation; field errors use fieldError above.
    const status = document.createElement("p");
    status.id = "fp-setup-pin-status";
    status.className = "modal-note";
    status.setAttribute("aria-live", "polite");

    const submit = document.createElement("button");
    submit.type = "button";
    submit.className = "btn";
    submit.textContent = t("setup.applock.set");
    submit.addEventListener("click", () => setPin(ctx));

    els = { pin, confirm, status, fieldError };
    container.append(
      heading,
      labelFor(pin, t("setup.applock.pin")),
      fieldError,
      labelFor(confirm, t("setup.applock.pin_confirm")),
      note,
      submit,
      status
    );
  },
};
