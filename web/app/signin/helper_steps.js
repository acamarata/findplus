/*
 * "Add the Find+ helper to Chrome": written steps, nothing opened for you.
 *
 * Purpose    : The one-time helper install as plain numbered steps with two
 *              copyable values (chrome://extensions and the helper folder).
 *              1.2 removed the "Show helper folder" and "Open Chrome
 *              extensions" buttons: they opened Finder and a Chrome tab on the
 *              owner's screen. Nothing in this file opens a window, a folder
 *              or a browser; Copy only writes to the clipboard.
 * Inputs     : The card's id prefix; postJson for the folder lookup.
 * Outputs    : { installHint, helperInstalled, helperFolder } and
 *              wireHelperSteps(), which fills the folder path on first open.
 * Constraints: The folder comes from POST /api/auth/google/helper/folder
 *              (copies the helper, returns its path, opens nothing). Until
 *              the daemon serves it, the catalog's plain path is shown.
 *              textContent only.
 */
"use strict";

import { t } from "../i18n.js";
import { button, el } from "./cards.js";

const FOLDER_ROUTE = "/api/auth/google/helper/folder";
const EXTENSIONS_URL = "chrome://extensions";

/** A value in a <code> box with its own Copy button. */
function copyable(prefix, key, value) {
  const row = el("span", "fp-signin-copy");
  const code = el("code", "fp-signin-copy-value", value);
  code.id = `${prefix}-google-helper-${key}`;
  const copy = button("btn btn-secondary btn-tiny fp-signin-copy-btn", t("signin.google.helper.copy"),
    `${prefix}-google-helper-${key}-copy`);
  copy.setAttribute("aria-label", t("signin.google.helper.copyLabel", { value: key === "folder"
    ? t("signin.google.helper.folderName") : EXTENSIONS_URL }));
  copy.addEventListener("click", () => copyText(code.textContent, copy));
  row.append(code, copy);
  return { row, code };
}

/** Write to the clipboard and say so on the button for two seconds. */
async function copyText(value, btn) {
  let ok = false;
  try {
    await navigator.clipboard.writeText(value);
    ok = true;
  } catch (_err) {
    ok = false;
  }
  btn.textContent = t(ok ? "signin.google.helper.copied" : "signin.google.helper.copyFailed");
  setTimeout(() => { btn.textContent = t("signin.google.helper.copy"); }, 2000);
}

/** The collapsed install steps. */
export function buildHelperSteps(prefix) {
  const wrap = el("details", "fp-signin-install");
  wrap.id = `${prefix}-google-helper-steps`;
  const summary = document.createElement("summary");
  summary.textContent = t("signin.google.helper.addTitle");
  const how = el("p", "fp-signin-how", t("signin.google.helper.addHow"));
  const list = el("ol", "fp-signin-steps");
  const ext = copyable(prefix, "extensions", EXTENSIONS_URL);
  const folder = copyable(prefix, "folder", t("signin.google.helper.folderFallback"));
  const step1 = el("li", "", t("signin.google.helper.step1"));
  step1.append(ext.row);
  const step3 = el("li", "", t("signin.google.helper.step3"));
  step3.append(folder.row);
  list.append(step1, el("li", "", t("signin.google.helper.step2")), step3,
    el("li", "", t("signin.google.helper.step4")));
  const installed = el("p", "fp-signin-how fp-signin-installed", t("signin.google.helper.installed"));
  installed.id = `${prefix}-google-helper-installed`;
  installed.hidden = true;
  wrap.append(summary, how, list, installed);
  return { installHint: wrap, helperInstalled: installed, helperFolder: folder.code };
}

/** Fill the real folder path the first time the steps are opened. */
export function wireHelperSteps(card, postJson) {
  let asked = false;
  card.installHint.addEventListener("toggle", async () => {
    if (!card.installHint.open || asked) return;
    asked = true;
    try {
      const answer = await postJson(FOLDER_ROUTE);
      if (answer && answer.path) card.helperFolder.textContent = answer.path;
    } catch (_err) {
      asked = false; // keep the plain path; ask again next time
    }
  });
}
