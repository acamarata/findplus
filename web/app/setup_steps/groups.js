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
 *              UAT6-N18: the step opened with no lead sentence, the name
 *              field had only a placeholder (gone the moment something is
 *              typed), Add with an empty name did nothing anyone could see,
 *              an account with no tracked device yet drew an empty bordered
 *              strip, and the untracked AirTag from the Devices step was
 *              still offered as a member. `labeled()` (groups_dialog_fields.js,
 *              already used by the group dialog's own Name field) gives this
 *              one a real `<label>` instead of forking a second copy of that
 *              wrapper; the aria-label stays too so nothing already reading
 *              it as "Group name" changes.
 */
"use strict";

import { t } from "../i18n.js";
import { renderBadge } from "../components/badge.js";
import { labeled } from "../groups_dialog_fields.js";
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
  // UAT6-N18: an empty name used to just return here, with nothing on screen
  // to say Add had even been pressed.
  if (!name) {
    els.error.textContent = t("groups.error.name_required");
    return;
  }
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

/** UAT6-N18: an untracked device (the Devices step's own AirTag example)
 * cannot report a location for a group to use, so it is never a sensible
 * member -- offering it invites a group that can never show more than
 * "Unknown" for that slot. */
function renderMembers(members, devices) {
  members.textContent = "";
  const tracked = devices.filter((d) => d.is_tracked);
  members.classList.toggle("fp-setup-group-members-empty", tracked.length === 0);
  if (!tracked.length) {
    const empty = document.createElement("p");
    empty.className = "fp-tab-hint";
    empty.textContent = t("setup.groups.no_devices");
    members.append(empty);
    return;
  }
  tracked.forEach((device) => members.append(memberRow(device)));
}

/** The name input plus its visible label -- split out of render() to keep
 * that function under the 50-line cap (PRI rule 7). Returns the bare input
 * (for `els.name` and the icon preview's live read) and the labelled wrapper
 * to mount instead of it. */
function buildNameField() {
  const name = document.createElement("input");
  name.type = "text";
  name.id = "fp-setup-group-name";
  name.placeholder = t("setup.groups.name_placeholder");
  // UAT4 N34: the placeholder was the field's only name, and a placeholder
  // disappears once something is typed -- an aria-label keeps a screen
  // reader's announcement even then (_notifications_telegram.js's own
  // aria-label pattern, N26).
  name.setAttribute("aria-label", t("setup.groups.name_placeholder"));
  // UAT6-N18: aria-label alone reads fine to a screen reader but LOOKS like
  // an unlabelled field to a sighted user -- the same `labeled()` wrapper
  // the group dialog's own Name field uses.
  return { name, nameField: labeled(t("groups.field.name"), name, name.id) };
}

async function refresh(ctx) {
  const groups = await ctx.api("/api/groups");
  els.list.textContent = "";
  groups.forEach((group) => els.list.append(groupRow(group)));

  // The devices step populated state.devices; if it was skipped entirely,
  // fetch the list rather than offering a member picker with nothing in it.
  let devices = ctx.state.devices || [];
  if (!devices.length) devices = (await ctx.api("/api/devices")).devices || [];
  renderMembers(els.members, devices);
}

export default {
  id: "groups",
  canSkip: true,
  render(container, ctx) {
    container.textContent = "";
    const heading = document.createElement("h2");
    heading.textContent = t("setup.groups.title");

    // UAT6-N18: the step opened straight into a bare list and a form with no
    // word about what a group is for.
    const lead = document.createElement("p");
    lead.className = "fp-wizard-lead";
    lead.textContent = t("setup.groups.lead");

    const list = document.createElement("div");
    list.id = "fp-setup-groups-list";

    const { name, nameField } = buildNameField();

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
    // nameField already carries `name` (labeled() moved it into its own
    // wrapper) -- appending `name` again here would rip it back out.
    container.append(
      heading, lead, list, nameField, pickers.iconWrap, pickers.colorWrap, members, error, add
    );
    container.addEventListener("click", (e) => pickers.closeIfOutside(e.target));
  },
  async onEnter(ctx) {
    await refresh(ctx);
  },
};
