/*
 * Channel picker: one checkbox per alert channel a rule can target.
 *
 * Purpose    : A rule can notify several channels at once (migration 0008), and
 *              a single <select> cannot say that. This is the checkbox set the
 *              add-rule dialog mounts in its place.
 * Inputs     : A host element, the currently `selected` ids, the `available`
 *              ids (the caller filters "native" out off macOS), an optional
 *              `labels` map the CALLER resolves through t(), and an optional
 *              `connected` set (UAT U11) -- an id present in `available` but
 *              absent from `connected` is flagged (a class the caller's CSS
 *              dims, plus whatever "(not connected)" suffix the caller put in
 *              `labels`) rather than disabled: a fresh install with nothing
 *              connected yet must still be able to create its first rule
 *              (`channels` is a required, non-empty field server-side), so
 *              disabling every box would have made that impossible. `connected`
 *              omitted (null/undefined) means "flag nothing", the pre-U11
 *              behaviour.
 * Outputs    : Checkboxes inside the host; readChannelPicker returns the checked
 *              ids, alphabetically sorted.
 * Constraints: Plain render/read functions, not a class, matching
 *              icon-picker.js (D-P2-2). No i18n import and no hardcoded
 *              sentence: the caller supplies every label, INCLUDING any
 *              "(not connected)" suffix -- this module owns no text of its own.
 */
"use strict";

const ALL_CHANNELS = ["telegram", "webhook", "whatsapp", "native"];

/** Mounts one checkbox per available channel, ticking every id in `selected`
 *  and flagging every id absent from `connected` (see `connected` above). */
export function renderChannelPicker(containerEl, { selected, available, labels = {}, connected = null }) {
  containerEl.textContent = "";
  for (const id of ALL_CHANNELS) {
    if (!available.includes(id)) continue;
    const isConnected = connected === null || connected.has(id);
    const label = document.createElement("label");
    label.className = "fp-channel-picker-option" + (isConnected ? "" : " fp-channel-picker-option--disconnected");
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
