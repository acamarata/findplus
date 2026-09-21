/*
 * The wizard Groups step's icon/colour pickers.
 *
 * Purpose    : Build the same panelled popover triggers the group dialog uses
 *              (groups_dialog_dom.js's pickerRow/renderIconPreview/
 *              renderColorPreview), so the wizard's Groups step never forks
 *              its own copy of that pattern (R-P2-28 point 2 — the bare
 *              48-swatch grid the visual gate found unreadable at every
 *              width). Split out of groups.js at the setup-step 150-line cap
 *              (specs/onboarding.md § 4).
 * Inputs     : `nameInput` — the group-name field, read live by the icon
 *              preview's bare-"letter" fallback initial.
 * Outputs    : { iconWrap, colorWrap, getIcon(), getColor(), reset(),
 *              closeIfOutside(target) } for the step to mount and read.
 * Constraints: groups_dialog_dom.js's own closePopoverIfOutside hardcodes the
 *              dialog's element ids, so the outside-click check here is a
 *              small local one built from this instance's own ids instead.
 */
"use strict";

import { t } from "../i18n.js";
import { createIconPicker } from "../components/icon-picker.js";
import { createColorPicker } from "../components/color-picker.js";
import {
  pickerRow, renderIconPreview, renderColorPreview,
  closeOpenPopover, clampPopoverToViewport,
} from "../groups_dialog_dom.js";

export const DEFAULT_ICON = "lucide:users";
export const DEFAULT_COLOR = "#27ae60";

function togglePopover(host, other) {
  other.hidden = true;
  host.hidden = !host.hidden;
  clampPopoverToViewport(host);
}

/** The two hidden inputs the pickers write their id/hex value into. */
function createHiddenInputs() {
  const iconInput = document.createElement("input");
  iconInput.type = "hidden";
  iconInput.value = DEFAULT_ICON;
  const colorInput = document.createElement("input");
  colorInput.type = "hidden";
  colorInput.value = DEFAULT_COLOR;
  return { iconInput, colorInput };
}

/** The two picker-row triggers, wired so opening one closes the other. */
function buildPickerRows(iconInput, colorInput) {
  const icon = pickerRow("fp-setup-group-icon", t("groups.field.icon"), iconInput, "fp-icon-swatch");
  const color = pickerRow("fp-setup-group-color", t("groups.field.color"), colorInput, "fp-color-swatch");
  icon.btn.addEventListener("click", () => togglePopover(icon.host, color.host));
  color.btn.addEventListener("click", () => togglePopover(color.host, icon.host));
  return { icon, color };
}

/** The public handle: wraps for mounting, getters, reset, and outside-click close. */
function buildPickerHandle(fields, iconPicker, colorPicker, icon, color, renderPreviews) {
  return {
    iconWrap: icon.wrap,
    colorWrap: color.wrap,
    getIcon: () => fields.icon.value,
    getColor: () => fields.color.value,
    reset() {
      fields.icon.value = DEFAULT_ICON;
      fields.color.value = DEFAULT_COLOR;
      iconPicker.setValue(DEFAULT_ICON);
      colorPicker.setValue(DEFAULT_COLOR);
      renderPreviews();
    },
    closeIfOutside(target) {
      const outsideIcon = !target.closest(`#${icon.host.id}, #${icon.btn.id}`);
      const outsideColor = !target.closest(`#${color.host.id}, #${color.btn.id}`);
      if ((!icon.host.hidden && outsideIcon) || (!color.host.hidden && outsideColor)) {
        closeOpenPopover(fields);
      }
    },
  };
}

export function createGroupPickers(nameInput) {
  const { iconInput, colorInput } = createHiddenInputs();
  const { icon, color } = buildPickerRows(iconInput, colorInput);

  // Shaped like groups_dialog_dom.js's own `fields`: renderIconPreview/
  // renderColorPreview read the five *Btn/icon/color/name properties;
  // closeOpenPopover (used by closeIfOutside below) also needs iconHost/
  // colorHost, so every property that helper touches is set here.
  const fields = {
    iconBtn: icon.btn, iconHost: icon.host, icon: iconInput,
    colorBtn: color.btn, colorHost: color.host, color: colorInput,
    name: nameInput,
  };
  function renderPreviews() {
    renderIconPreview(fields);
    renderColorPreview(fields);
  }

  const iconPicker = createIconPicker(icon.host, {
    value: iconInput.value,
    onChange: (id) => { iconInput.value = id; renderPreviews(); icon.host.hidden = true; },
    letterLabel: t("devices.field.letter"),
  });
  const colorPicker = createColorPicker(color.host, {
    value: colorInput.value,
    onChange: (hex) => { colorInput.value = hex; renderPreviews(); color.host.hidden = true; },
    customLabel: t("devices.field.customColor"),
  });
  renderPreviews();

  return buildPickerHandle(fields, iconPicker, colorPicker, icon, color, renderPreviews);
}
