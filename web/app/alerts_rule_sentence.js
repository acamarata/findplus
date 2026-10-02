/*
 * The rule dialog's plain-words sentence, and the group explainer.
 *
 * Purpose    : "Tell me on Telegram when Sam Bag leaves School." says what a
 *              rule does far better than a row of ticks. Pure functions so the
 *              dialog, the rules table and the tests all read the same sentence.
 * Inputs     : ruleSentence({ channels, who, enter, exit, place, isGroup }):
 *              channel labels, the tracker or group name ("" if not chosen yet),
 *              the two event ticks and the place name ("" if none).
 *              groupNote(group): a group row from /api/groups.
 * Outputs    : A sentence string; stillNeeded(parts) -> the list of missing bits.
 * Constraints: No DOM, no network. Every word comes from the catalog.
 */
"use strict";

import { t } from "./i18n.js";

function listJoin(items) {
  try {
    return new Intl.ListFormat(document.documentElement.lang || undefined, {
      style: "long", type: "conjunction",
    }).format(items);
  } catch (_) {
    return items.join(", ");
  }
}

function eventsText(enter, exit) {
  if (enter && exit) return t("alerts.sentence.arrivesOrLeaves");
  if (enter) return t("alerts.sentence.arrives");
  if (exit) return t("alerts.sentence.leaves");
  return t("alerts.sentence.noEvent");
}

/** "Tell me on Telegram and Webhook when Sam Bag leaves School." */
export function ruleSentence({ channels, who, enter, exit, place, isGroup }) {
  const vars = {
    who: who || t(isGroup ? "alerts.sentence.aGroup" : "alerts.sentence.aTracker"),
    events: eventsText(enter, exit),
    place: place || t("alerts.sentence.aPlace"),
  };
  return channels.length
    ? t("alerts.sentence.withChannel", { ...vars, channels: listJoin(channels) })
    : t("alerts.sentence.noChannel", vars);
}

/** The labels of what is still missing before Save can work (empty: ready). */
export function stillNeeded({ name, who, isGroup, enter, exit, channels, place }) {
  const missing = [];
  if (!name.trim()) missing.push(t("alerts.sentence.needName"));
  if (!place) missing.push(t("alerts.sentence.needPlace"));
  if (!who) missing.push(t(isGroup ? "alerts.sentence.needGroup" : "alerts.sentence.needTracker"));
  if (!enter && !exit) missing.push(t("alerts.sentence.needEvent"));
  if (channels === 0) missing.push(t("alerts.sentence.needChannel"));
  return missing;
}

/** How a group's quorum and stale window decide "the group arrived", in words. */
export function groupNote(group) {
  if (!group) return "";
  const q = String(group.quorum);
  const rule = ["any", "majority", "all"].includes(q)
    ? t(`alerts.groupNote.${q}`)
    : t("alerts.groupNote.count", { count: q });
  const note = t("alerts.groupNote.intro", { rule });
  return group.stale_after_minutes
    ? `${note} ${t("alerts.groupNote.stale", { minutes: group.stale_after_minutes })}`
    : note;
}
