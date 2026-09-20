/*
 * Onboarding step 4 — Groups (optional).
 *
 * Purpose    : Show the groups that already exist and offer one inline form to
 *              create another from the devices picked a step earlier
 *              (specs/onboarding.md § 4 row 4).
 * Inputs     : ctx.api / ctx.postJson / ctx.state, handed down by the Wizard.
 * Outputs    : POST /api/groups, once per Add click.
 * Constraints: Add creates the group there and then, not on Next, so Skip is a
 *              true no-op. Colour and icon come from the shared pickers
 *              (D-P2-2/D-P2-3), never from a second local widget.
 */
"use strict";

import { t } from "../i18n.js";
import { renderBadge } from "../components/badge.js";

const DEFAULT_ICON = "lucide:users";
const DEFAULT_COLOR = "#27ae60";

/** The live step's elements, replaced on every render. */
let els = null;

function memberCheckbox(device) {
  const row = document.createElement("label");
  row.className = "setting-row";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.dataset.deviceId = device.device_id;
  const name = document.createElement("span");
  name.textContent = device.label || device.name || device.device_id;
  row.append(box, name);
  return row;
}

function groupRow(group) {
  const row = document.createElement("div");
  row.className = "fp-dialog-field";
  row.append(
    renderBadge({
      icon: group.icon || DEFAULT_ICON,
      color: group.color,
      name: group.name,
      size: 24,
    })
  );
  const name = document.createElement("span");
  name.textContent = group.name;
  row.append(name);
  return row;
}

async function mountPickers(host) {
  const [icons, colors] = await Promise.all([
    import("../components/icon-picker.js"),
    import("../components/color-picker.js"),
  ]);
  icons.createIconPicker(host, {
    value: els.icon,
    onChange: (value) => {
      els.icon = value;
    },
    letterLabel: t("devices.field.letter"),
  });
  colors.createColorPicker(host, {
    value: els.color,
    onChange: (value) => {
      els.color = value;
    },
    customLabel: t("devices.field.customColor"),
  });
}

async function addGroup(ctx) {
  const name = els.name.value.trim();
  if (!name) return;
  const memberIds = [...els.members.querySelectorAll("input:checked")].map(
    (box) => box.dataset.deviceId
  );
  await ctx.postJson("/api/groups", {
    name,
    color: els.color,
    icon: els.icon,
    member_ids: memberIds,
  });
  els.name.value = "";
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
  devices.forEach((device) => els.members.append(memberCheckbox(device)));
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

    const pickers = document.createElement("div");
    const members = document.createElement("div");
    members.id = "fp-setup-group-members";

    const add = document.createElement("button");
    add.type = "button";
    add.className = "btn";
    add.textContent = t("setup.groups.add");
    add.addEventListener("click", () => {
      addGroup(ctx).catch((err) => ctx.showAlert(err.message, "err"));
    });

    els = { list, name, members, icon: DEFAULT_ICON, color: DEFAULT_COLOR };
    mountPickers(pickers).catch(() => {});
    container.append(heading, list, name, pickers, members, add);
  },
  async onEnter(ctx) {
    await refresh(ctx);
  },
};
