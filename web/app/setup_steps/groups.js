/*
 * Onboarding step 4 — Groups (optional).
 *
 * Purpose    : Show the groups that already exist and offer one inline form to
 *              create another from the devices picked a step earlier
 *              (specs/onboarding.md § 4 row 4).
 * Inputs     : ctx.api / ctx.postJson / ctx.state, handed down by the Wizard.
 * Outputs    : POST /api/groups, once per Add click.
 * Constraints: Add creates the group there and then, not on Next, so Skip is a
 *              true no-op. Icon/colour pickers live in _group_pickers.js
 *              (R-P2-28 point 2, the setup-step 150-line cap). The member
 *              checklist uses `.fp-member-row`, the same class the dialog's
 *              own member list draws with, instead of `.setting-row` (F1:
 *              that row is `justify-content: space-between` with nothing
 *              between a checkbox at the left edge and a name at the right).
 */
"use strict";

import { t } from "../i18n.js";
import { renderBadge } from "../components/badge.js";
import { createGroupPickers, DEFAULT_ICON } from "./_group_pickers.js";

/** The live step's elements and picker handle, replaced on every render. */
let els = null;
let pickers = null;

function memberRow(device) {
  const row = document.createElement("label");
  row.className = "fp-member-row";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.dataset.deviceId = device.device_id;
  const badge = document.createElement("span");
  badge.appendChild(
    renderBadge({ icon: device.icon || "letter", color: device.color, label: device.label, name: device.name, size: 16 })
  );
  const name = document.createElement("span");
  name.textContent = device.label || device.name || device.device_id;
  row.append(box, badge, name);
  return row;
}

/** N45: a duplicate name (409) used to only log to the console -- ctx.showAlert
 * writes into #alert inside #app-shell, hidden for the whole time the wizard
 * is open (applock.js's own comment on the same trap). role="alert" makes
 * this line's text change announced, the same way applock's own field error
 * is meant to read even without an aria-live attribute of its own. */
function groupErrorEl() {
  const error = document.createElement("p");
  error.className = "fp-dialog-error";
  error.id = "fp-setup-group-error";
  error.setAttribute("role", "alert");
  return error;
}

function groupRow(group) {
  const row = document.createElement("div");
  row.className = "fp-dialog-field";
  row.append(
    renderBadge({ icon: group.icon || DEFAULT_ICON, color: group.color, name: group.name, size: 24 })
  );
  const name = document.createElement("span");
  name.textContent = group.name;
  row.append(name);
  return row;
}

async function addGroup(ctx) {
  const name = els.name.value.trim();
  if (!name) return;
  const memberIds = [...els.members.querySelectorAll("input:checked")].map(
    (box) => box.dataset.deviceId
  );
  // UAT U16: Add used to create a zero-member group with no word about it,
  // which then showed "Unknown" in the list -- a quorum with nobody to count
  // is never meaningful.
  if (!memberIds.length) {
    els.error.textContent = t("groups.error.members_required");
    return;
  }
  els.error.textContent = "";
  await ctx.postJson("/api/groups", {
    name, color: pickers.getColor(), icon: pickers.getIcon(), member_ids: memberIds,
  });
  els.name.value = "";
  pickers.reset();
  await refresh(ctx);
}

async function refresh(ctx) {
  const groups = await ctx.api("/api/groups");
  els.list.textContent = "";
  groups.forEach((group) => els.list.append(groupRow(group)));

  // The devices step populated state.devices; if it was skipped entirely,
  // fetch the list rather than offering a member picker with nothing in it.
  let devices = ctx.state.devices || [];
  if (!devices.length) devices = (await ctx.api("/api/devices")).devices || [];
  els.members.textContent = "";
  devices.forEach((device) => els.members.append(memberRow(device)));
}

export default {
  id: "groups",
  canSkip: true,
  render(container, ctx) {
    container.textContent = "";
    const heading = document.createElement("h2");
    heading.textContent = t("setup.groups.title");

    const list = document.createElement("div");
    list.id = "fp-setup-groups-list";

    const name = document.createElement("input");
    name.type = "text";
    name.id = "fp-setup-group-name";
    name.placeholder = t("setup.groups.name_placeholder");
    // UAT4 N34: the placeholder was the field's only name, and a placeholder
    // disappears once something is typed -- an aria-label keeps a screen
    // reader's announcement even then (_notifications_telegram.js's own
    // aria-label pattern, N26).
    name.setAttribute("aria-label", t("setup.groups.name_placeholder"));

    // Built after `name` exists: the icon preview reads it live for the
    // bare-"letter" fallback initial.
    pickers = createGroupPickers(name);

    const members = document.createElement("div");
    members.id = "fp-setup-group-members";

    const add = document.createElement("button");
    add.type = "button";
    add.id = "fp-setup-group-add";
    add.className = "btn";
    add.textContent = t("setup.groups.add");
    add.addEventListener("click", () => {
      addGroup(ctx).catch((err) => {
        els.error.textContent = err.message;
      });
    });

    const error = groupErrorEl();

    els = { list, name, members, error };
    container.append(
      heading, list, name, pickers.iconWrap, pickers.colorWrap, members, error, add
    );
    container.addEventListener("click", (e) => pickers.closeIfOutside(e.target));
  },
  async onEnter(ctx) {
    await refresh(ctx);
  },
};
