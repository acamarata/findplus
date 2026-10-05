/*
 * A person's avatar as a button that opens the editor at the icon picker.
 *
 * Purpose    : Icons and colours for people existed in the person editor but
 *              nobody found them. Every person avatar (Person page header,
 *              people cards, and any new list that wants one) is now this
 *              button: "Change Ali's icon and colour".
 * Inputs     : A person ({id, name, icon, color}) and `onSaved()` to run after a
 *              successful save.
 * Outputs    : A <button class="person-avatar-btn"> holding the person's badge.
 * Constraints: createElement/textContent only. The badge inside is decoration
 *              (aria-hidden); the button's aria-label carries the meaning. The
 *              editor module is imported on click, so this file adds no weight
 *              or import cycle to the pages that draw avatars.
 * Reuse      : person_head.js, groups_person_card.js; the Latest and People
 *              rows may call personAvatarButton() the same way.
 */
"use strict";

import { t } from "./i18n.js";
import { renderBadge } from "./components/badge.js";

/** Open the person editor with focus on the icon picker. */
export async function openIconEditor(person, onSaved) {
  const { openPersonEditor } = await import("./person_editor.js");
  await openPersonEditor(person.id, onSaved, { focus: "icon" });
}

/**
 * The avatar button. `size` is the badge size in px (44 on the Person page, 24
 * on a card); the button itself keeps a 32 px minimum hit area.
 */
export function personAvatarButton(person, { size = 24, onSaved = null } = {}) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "person-avatar-btn";
  btn.setAttribute("aria-label", t("personColours.avatarButton", { name: person.name }));
  btn.title = btn.getAttribute("aria-label");
  const badge = renderBadge({ icon: person.icon, color: person.color, label: null, name: person.name, size });
  badge.setAttribute("aria-hidden", "true");
  btn.appendChild(badge);
  btn.addEventListener("click", (event) => {
    event.stopPropagation(); // a card's own click selects the group; this only edits
    openIconEditor(person, onSaved).catch((err) => console.error("person editor failed", err));
  });
  return btn;
}
