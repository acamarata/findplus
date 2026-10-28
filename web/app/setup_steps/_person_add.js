/*
 * Onboarding step 4 (People): the compact "Add a person" form.
 *
 * Purpose    : Let someone name a person and tick the trackers they carry, right
 *              in the step, next to the "We found people" suggestions. Groups are
 *              no longer the first thing this step asks for (1.3, U30).
 * Inputs     : `ctx.postJson` (handed down by the Wizard), an `onAdded()` callback,
 *              and the device rows via `setDevices()`.
 * Outputs    : POST /api/people { name, kind: "person", member_ids }, once per
 *              Add click. The colour is left for the daemon to pick.
 * Constraints: createElement/textContent only. A person is created there and then
 *              (not on Next), so Skip stays a true no-op. Errors render in the
 *              step's own role="alert" line, never in #alert, which is hidden
 *              while the wizard is open. The member checklist is the shared
 *              groups_members.js one.
 */
"use strict";

import { t } from "../i18n.js";
import { renderMemberList } from "../groups_members.js";
import { labeled } from "../groups_dialog_fields.js";
import { duplicateNameMessage } from "../dialog_errors.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Add one person from the typed name and ticked trackers. Returns false when refused. */
async function addPerson(ctx, ui) {
  const name = ui.name.value.trim();
  ui.status.textContent = "";
  if (!name) {
    ui.error.textContent = t("groups.error.name_required");
    return false;
  }
  const ids = [...ui.members.querySelectorAll("input[data-device-id]:checked")].map((b) => b.dataset.deviceId);
  if (!ids.length) {
    ui.error.textContent = t("groups.error.members_required");
    return false;
  }
  ui.error.textContent = "";
  await ctx.postJson("/api/people", { name, kind: "person", member_ids: ids });
  ui.name.value = "";
  ui.status.textContent = t("setup.groups.person_added", { name });
  return true;
}

/** Build the form. `setDevices(rows)` (re)draws the tracker checklist. */
export function buildPersonAdd(ctx, { onAdded }) {
  const root = el("section", "fp-setup-person");
  root.id = "fp-setup-person-add";
  const name = el("input");
  name.type = "text";
  name.id = "fp-setup-person-name";
  name.maxLength = 40;
  name.placeholder = t("setup.groups.person_placeholder");
  const members = el("div");
  members.id = "fp-setup-person-members";
  members.className = "fp-setup-group-members";
  const error = el("p", "fp-dialog-error");
  error.id = "fp-setup-person-error";
  error.setAttribute("role", "alert");
  const status = el("p", "fp-wizard-summary");
  status.id = "fp-setup-person-status";
  status.setAttribute("role", "status");
  const add = el("button", "btn", t("setup.groups.person_add"));
  add.type = "button";
  add.id = "fp-setup-person-add-btn";
  const ui = { name, members, error, status };
  add.addEventListener("click", () => {
    addPerson(ctx, ui)
      .then((added) => { if (added && onAdded) return onAdded(); })
      .catch((err) => {
        ui.error.textContent = duplicateNameMessage(err, "groups.error.duplicate_name", name.value.trim()) || err.message;
      });
  });
  root.append(
    el("h3", "fp-wizard-subhead", t("setup.groups.person_title")),
    labeled(t("groups.field.name"), name, name.id),
    members, error, add, status,
  );
  return {
    root,
    setDevices(devices) {
      members.classList.toggle("fp-setup-group-members-empty", devices.length === 0);
      renderMemberList(members, devices, { wizard: true });
    },
  };
}
