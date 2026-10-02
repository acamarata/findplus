/*
 * "We noticed these places": the plain-words lines on one suggestion card.
 *
 * Purpose    : Turn a candidate from GET /api/places/suggestions into short sentences
 *              ("9 visits on 9 days, usually 8:10 AM to 3:00 PM on weekdays").
 * Inputs     : One candidate {visits, days, nights, typical, kind_guess, trackers}.
 * Outputs    : Strings only; no DOM.
 * Constraints: A guess is always a question ("Home?"): Find+ never names a place.
 *              Times use the browser's own 12 or 24 hour style.
 */
"use strict";

import { plural, t } from "./i18n.js";

/** "8:10 AM" for a minute of the day. */
export function clock(minute) {
  const at = new Date(2000, 0, 1, Math.floor(minute / 60) % 24, minute % 60);
  return at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** "Home?", "School or work?" or "Regular stop". */
export function guessTitle(c) {
  return t(`places.noticed.guess.${c.kind_guess}`);
}

/** "9 visits on 9 days, usually 8:10 AM to 3:00 PM on weekdays". */
export function usuallyLine(c) {
  const when = t("places.noticed.usually", {
    from: clock(c.typical.start_min),
    to: clock(c.typical.end_min),
    days: t(`places.noticed.days.${c.typical.days}`),
  });
  const counts = plural("places.noticed.visits", c.visits, { count: c.visits });
  return `${counts} ${plural("places.noticed.onDays", c.days, { count: c.days })}, ${when}`;
}

/** Extra facts: nights there (only when there were some) and who was seen. */
export function factsLine(c) {
  const parts = [];
  if (c.nights > 0) parts.push(plural("places.noticed.nights", c.nights, { count: c.nights }));
  parts.push(t("places.noticed.seenBy", { names: c.trackers.join(", ") }));
  return parts.join(" · ");
}
