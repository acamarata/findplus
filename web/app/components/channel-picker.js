/*
 * Channel picker: one checkbox per alert channel a rule can target.
 *
 * Purpose    : A rule can notify several channels at once (migration 0008), and
 *              a single <select> cannot say that. This is the checkbox set the
 *              add-rule dialog mounts in its place.
 * Inputs     : A host element, the currently `selected` ids, the `available`
 *              ids (the caller filters "native" out off macOS), and an optional
 *              `labels` map the CALLER resolves through t().
 * Outputs    : Checkboxes inside the host; readChannelPicker returns the checked
 *              ids, alphabetically sorted.
 * Constraints: Plain render/read functions, not a class, matching
 *              icon-picker.js (D-P2-2). No i18n import and no hardcoded
 *              sentence: the caller supplies every label. createElement only,
 *              never raw markup.
 */
"use strict";

const ALL_CHANNELS = ["telegram", "webhook", "whatsapp", "native"];

/** Mounts one checkbox per available channel, ticking every id in `selected`. */
export function renderChannelPicker(containerEl, { selected, available, labels = {} }) {
  containerEl.textContent = "";
  for (const id of ALL_CHANNELS) {
    if (!available.includes(id)) continue;
    const label = document.createElement("label");
    label.className = "fp-channel-picker-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = id;
    input.checked = selected.includes(id);
    input.dataset.channel = id;
    label.append(input, document.createTextNode(" " + (labels[id] || id)));
    containerEl.append(label);
  }
}

/** The checked channel ids, alphabetically sorted whatever the DOM order is. */
export function readChannelPicker(containerEl) {
  return Array.from(containerEl.querySelectorAll("input[type=checkbox]:checked"))
    .map((el) => el.dataset.channel)
    .sort();
}
