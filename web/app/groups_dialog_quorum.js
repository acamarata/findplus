/*
 * Group dialog: the custom quorum number, checked before it can fail.
 *
 * Purpose    : A custom quorum larger than the member count saved without a word
 *              and then never fired, and a typed 50 reached the server as a raw
 *              422 (UAT #11). The number is clamped to 1-20 when the box is left,
 *              a warning shows while it exceeds the ticked members, and Save is
 *              refused for a number the server would reject.
 * Inputs     : The dialog's `fields` (groups_dialog_dom.js's shape).
 * Outputs    : The warning line's text; a clamped quorum box.
 * Constraints: The warning never blocks Save (a group may be saved first and its
 *              members added later); only an out-of-range number does.
 */
"use strict";

import { t } from "./i18n.js";

const MIN = 1;
const MAX = 20;

const memberCount = (fields) => fields.members.querySelectorAll("input[data-device-id]:checked").length;
const typed = (fields) => Number(fields.quorumN.value);

/** Show or hide the warning under the quorum row for the current values. */
export function refreshQuorumWarning(fields) {
  const warn = fields.quorumWarn;
  if (!warn) return;
  const n = typed(fields);
  let message = "";
  if (fields.quorum.value === "custom" && fields.quorumN.value !== "") {
    if (!Number.isInteger(n) || n < MIN || n > MAX) {
      message = t("groups.quorumRange", { min: MIN, max: MAX });
    } else if (n > memberCount(fields)) {
      message = t("groups.quorumTooHigh", { n, members: memberCount(fields) });
    }
  }
  warn.textContent = message;
  warn.hidden = !message;
}

/** The message for a custom quorum the server would reject, or null. */
export function quorumProblem(fields) {
  if (fields.quorum.value !== "custom") return null;
  const n = typed(fields);
  const ok = fields.quorumN.value !== "" && Number.isInteger(n) && n >= MIN && n <= MAX;
  return ok ? null : t("groups.quorumRange", { min: MIN, max: MAX });
}

/** Wire the live warning and the clamp on leaving the box. */
export function wireQuorumGuard(fields) {
  const refresh = () => refreshQuorumWarning(fields);
  fields.quorum.addEventListener("change", refresh);
  fields.quorumN.addEventListener("input", refresh);
  fields.quorumN.addEventListener("change", () => {
    const n = Math.round(typed(fields));
    if (fields.quorumN.value !== "" && Number.isFinite(n)) {
      fields.quorumN.value = String(Math.min(MAX, Math.max(MIN, n)));
    }
    refresh();
  });
  fields.members.addEventListener("change", refresh);
}
