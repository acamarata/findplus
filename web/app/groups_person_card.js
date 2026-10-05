/*
 * Groups tab: how a person's or pet's card reads.
 *
 * Purpose    : People are kept in the same list as groups, but they are not
 *              groups. A card says how many trackers the person has and where
 *              they are now, in the Person page's own words. It never says "alerts
 *              when most members arrive", and a person with one tracker is never
 *              shown as "Only 1 reporting": one tracker reporting is normal.
 * Inputs     : A group dict with kind "person" or "pet"; GET /api/people/{id}/now.
 * Outputs    : A meta line element, and the where-now sentence written into the
 *              card's explanation slot.
 * Constraints: createElement/textContent only. A failed lookup leaves the slot
 *              empty rather than drawing an error on a card.
 */
"use strict";

import { api } from "./api.js";
import { plural, t } from "./i18n.js";
import { personAvatarButton } from "./person_avatar.js";

/** True for the cards that are people or pets, not groups. */
export const isPerson = (group) => group.kind === "person" || group.kind === "pet";

/** The card's icon slot for a person: their avatar, as a button that opens the editor at the icon picker. */
export function personCardIcon(group, onSaved) {
  const slot = document.createElement("span");
  slot.className = "fp-card-icon";
  slot.appendChild(personAvatarButton(group, { size: 24, onSaved }));
  return slot;
}

/** "4 trackers", with "Pet" in front for a pet. */
export function personMeta(group) {
  const wrap = document.createElement("span");
  wrap.className = "fp-card-meta";
  const n = group.members.length;
  const kind = group.kind === "pet" ? `${t("person.kind.pet")} · ` : "";
  const line = document.createElement("span");
  line.textContent = kind + plural("groups.card.trackers", n, { count: n });
  wrap.appendChild(line);
  return wrap;
}

/** Write "Likely at School, seen 7 min ago" under the buttons. */
export async function fillWhereNow(card, group) {
  let now;
  try {
    now = await api(`/api/people/${group.id}/now`);
  } catch (_) {
    return;
  }
  const slot = card.isConnected && card.querySelector(".fp-card-explain");
  if (!slot || !now || !now.text) return;
  slot.textContent = now.text;
  slot.hidden = false;
}
