/*
 * Groups tab: the two plain-words lines on a group card.
 *
 * Purpose    : A card used to show only a name, avatars and a verdict pill. This
 *              adds (1) a meta line saying how many members the group has and
 *              when it alerts, with a warning when members are not tracked (Find+
 *              never polls them, so they can never report), and (2) an
 *              explanation line under the buttons for a verdict that is not
 *              "together" (the server's own sentence, so the reason is visible
 *              without hovering).
 * Inputs     : A group (members, quorum), the device cache by id, a presence
 *              response.
 * Outputs    : DOM elements built with createElement/textContent.
 * Constraints: The explanation sits below the Edit and Delete buttons so it can
 *              appear after the presence call without moving them under a tap.
 */
"use strict";

import { t, plural } from "./i18n.js";

function span(className, text) {
  const el = document.createElement("span");
  el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

/** "alerts when most members arrive" for a stored quorum value. */
export function quorumPhrase(quorum) {
  if (/^\d+$/.test(String(quorum))) return t("groups.card.rule.custom", { n: Number(quorum) });
  return t(`groups.card.rule.${quorum}`);
}

/** Members tracked and untracked, by looking each up in the device cache. */
function untrackedCount(group, devicesById) {
  return group.members.filter((m) => {
    const device = devicesById.get(m.device_id);
    return device && !device.is_tracked;
  }).length;
}

/** "3 members, alerts when most members arrive" plus a warning when some are untracked. */
export function metaLine(group, devicesById) {
  const wrap = span("fp-card-meta");
  const count = group.members.length;
  wrap.append(span("", `${plural("groups.card.members", count, { count })} · ${quorumPhrase(group.quorum)}`));
  const off = untrackedCount(group, devicesById);
  if (off > 0) {
    wrap.append(span("fp-card-meta-warn", plural("groups.card.untracked", off, { count: off })));
  }
  return wrap;
}

/** The empty explanation slot (filled by fillExplanation once presence arrives). */
export function explainSlot() {
  const el = span("fp-card-explain");
  el.hidden = true;
  return el;
}

/** Show the server's sentence for any verdict that is not plainly "together". */
export function fillExplanation(card, presence) {
  const el = card.querySelector(".fp-card-explain");
  if (!el) return;
  const text = presence.verdict === "all_together" ? "" : presence.note || "";
  el.textContent = text;
  el.hidden = !text;
}
