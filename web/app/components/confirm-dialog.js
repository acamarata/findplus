/*
 * Shared in-app confirm/alert dialog (UAT6-N21, WP-H).
 *
 * Purpose    : Replace every native window.confirm()/window.prompt()/
 *              window.alert() call under web/app -- they read as
 *              "127.0.0.1:8747 says…", look unfinished, and window.prompt()
 *              is unsupported in the Tauri desktop shell's WebView. One
 *              <dialog>, built once and reused, replaces every call site.
 * Inputs     : confirmDialog({ title, body, confirmLabel, cancelLabel,
 *              danger, input }). `body` may carry the same "\n\n" paragraph
 *              breaks window.confirm() rendered -- CSS `white-space:
 *              pre-line` (confirm-dialog.css) reproduces them, never markup.
 *              `input`, when given ({ requireText, label, placeholder }),
 *              adds a text field and keeps Confirm disabled until its value
 *              matches `requireText` -- window.prompt()'s "type DELETE to
 *              confirm" pattern folded into the one dialog instead of a
 *              second native prompt(). alertDialog({ title, body,
 *              confirmLabel }) is the same chrome with no Cancel button, for
 *              window.alert()'s call sites.
 * Outputs    : confirmDialog resolves true (Confirm clicked, which can only
 *              happen while it is enabled -- never true against an unmet
 *              `input.requireText`) or false (Cancel or Escape). alertDialog
 *              resolves once dismissed.
 * Constraints: One <dialog>, reused serially -- every caller awaits its own
 *              call before the next one can open. Escape and Cancel both
 *              resolve false; a native <dialog> already traps Tab focus and
 *              closes on Escape on its own (dialog-trap.js's own comment:
 *              only the two div-based `.modal`s need that helper). `danger`
 *              starts focus on Cancel so a destructive action is never the
 *              accidental Enter default -- unless `input.requireText` is
 *              set, in which case Confirm is already disabled until the
 *              exact text is typed, so focus goes to the field instead.
 *              Focus always returns to whatever was focused when the dialog
 *              opened. Built with createElement/textContent, never
 *              innerHTML.
 */
"use strict";

import { t } from "../i18n.js";

let dlg = null;
let els = null;

/** Built once, lazily -- the same pattern devices_dialog.js's ensureDialog()
 *  uses, so a page that never confirms anything never pays for this DOM. */
function build() {
  const dialog = document.createElement("dialog");
  dialog.id = "fp-confirm-dialog";
  dialog.setAttribute("role", "alertdialog");
  dialog.setAttribute("aria-labelledby", "fp-confirm-dialog-title");
  dialog.setAttribute("aria-describedby", "fp-confirm-dialog-body");

  const form = document.createElement("form");
  form.method = "dialog";

  const title = document.createElement("h2");
  title.id = "fp-confirm-dialog-title";
  const body = document.createElement("p");
  body.id = "fp-confirm-dialog-body";
  body.className = "fp-confirm-dialog-body";

  const inputWrap = document.createElement("div");
  inputWrap.className = "fp-dialog-field";
  inputWrap.hidden = true;
  const inputLabel = document.createElement("label");
  inputLabel.htmlFor = "fp-confirm-dialog-input";
  const input = document.createElement("input");
  input.type = "text";
  input.id = "fp-confirm-dialog-input";
  input.autocomplete = "off";
  inputWrap.append(inputLabel, input);

  const confirmBtn = document.createElement("button");
  confirmBtn.type = "button";
  confirmBtn.id = "fp-confirm-dialog-confirm";
  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.id = "fp-confirm-dialog-cancel";
  const footer = document.createElement("footer");
  footer.append(confirmBtn, cancelBtn);

  form.append(title, body, inputWrap, footer);
  dialog.appendChild(form);
  document.body.appendChild(dialog);
  return { title, body, inputWrap, inputLabel, input, confirmBtn, cancelBtn };
}

function ensure() {
  if (!dlg) {
    els = build();
    dlg = document.getElementById("fp-confirm-dialog");
  }
  return els;
}

/** Text/class for the two buttons; `showCancel` false hides Cancel entirely
 *  for alertDialog()'s one-button chrome. */
function configureButtons({ confirmLabel, cancelLabel, danger, showCancel }) {
  els.confirmBtn.textContent = confirmLabel || t("common.confirm");
  els.confirmBtn.className = danger ? "btn btn-danger" : "btn";
  els.cancelBtn.hidden = !showCancel;
  els.cancelBtn.textContent = showCancel ? cancelLabel || t("common.cancel") : "";
}

/** Shows/hides and seeds the optional text field. Returns the text Confirm
 *  requires before it enables, or null when nothing is required. */
function configureInput(input) {
  els.inputWrap.hidden = !input;
  if (!input) return null;
  els.inputLabel.textContent = input.label || "";
  els.input.value = "";
  els.input.placeholder = input.placeholder || "";
  return input.requireText != null ? input.requireText : null;
}

/** Wires this open's listeners and resolves `resolve` exactly once, on the
 *  <dialog>'s own "close" event -- fired whether Confirm, Cancel or Escape
 *  closed it, so there is one exit path to clean up and restore focus from. */
function settle({ opener, requireText, danger }, resolve) {
  let result = false;
  const onInput = requireText == null ? null : () => {
    els.confirmBtn.disabled = els.input.value !== requireText;
  };
  if (onInput) els.input.addEventListener("input", onInput);

  const onConfirm = () => {
    if (els.confirmBtn.disabled) return;
    result = true;
    dlg.close();
  };
  const onCancel = () => dlg.close();
  const onClose = () => {
    els.confirmBtn.removeEventListener("click", onConfirm);
    els.cancelBtn.removeEventListener("click", onCancel);
    dlg.removeEventListener("close", onClose);
    if (onInput) els.input.removeEventListener("input", onInput);
    if (opener && typeof opener.focus === "function") opener.focus();
    resolve(result);
  };

  els.confirmBtn.addEventListener("click", onConfirm);
  els.cancelBtn.addEventListener("click", onCancel);
  dlg.addEventListener("close", onClose);

  dlg.showModal();
  if (requireText != null) els.input.focus();
  else if (danger) els.cancelBtn.focus();
}

/**
 * Ask a yes/no (or type-to-confirm) question with the shared dialog chrome.
 * See the file header for the full contract.
 */
export function confirmDialog({
  title, body, confirmLabel, cancelLabel, danger = false, input = null,
} = {}) {
  ensure();
  const opener = document.activeElement;
  const showCancel = cancelLabel !== null;

  els.title.textContent = title || "";
  els.body.textContent = body || "";
  configureButtons({ confirmLabel, cancelLabel, danger, showCancel });
  const requireText = configureInput(input);
  els.confirmBtn.disabled = requireText != null && requireText !== "";

  return new Promise((resolve) => settle({ opener, requireText, danger }, resolve));
}

/** A message with only one way out -- window.alert()'s call sites. */
export function alertDialog({ title, body, confirmLabel } = {}) {
  return confirmDialog({
    title, body, confirmLabel: confirmLabel || t("common.ok"), cancelLabel: null,
  });
}
