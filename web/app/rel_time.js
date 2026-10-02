/*
 * Relative times for lists ("12 minutes ago", "yesterday").
 *
 * Purpose    : A list of arrivals and departures reads faster as "12 minutes
 *              ago" than as "Oct 1, 7:16 PM EDT". The exact time stays one
 *              hover away (the caller puts it in a title).
 * Inputs     : An ISO timestamp, and optionally "now" (tests pin it).
 * Outputs    : relativeTime(iso, now) -> text; absoluteTime(iso) -> text with
 *              the zone abbreviation, the same shape the delivery log uses.
 * Constraints: Pure, no network. Uses Intl.RelativeTimeFormat in the page's
 *              language; anything older than a week falls back to the date.
 */
"use strict";

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function formatter() {
  try {
    return new Intl.RelativeTimeFormat(document.documentElement.lang || undefined, { numeric: "auto" });
  } catch (_) {
    return new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  }
}

/** "Oct 1, 7:16 PM EDT": date, time and zone together. */
export function absoluteTime(iso) {
  const d = new Date(iso);
  const datePart = d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const zone = d.toLocaleTimeString([], { timeZoneName: "short" }).split(" ").pop();
  return `${datePart} ${zone}`;
}

/** "just now", "12 minutes ago", "3 hours ago", "yesterday", "4 days ago"; older: the date. */
export function relativeTime(iso, now = Date.now()) {
  const diff = now - new Date(iso).getTime();
  const rtf = formatter();
  if (Number.isNaN(diff)) return "";
  if (diff < MINUTE) return rtf.format(0, "second");
  if (diff < HOUR) return rtf.format(-Math.floor(diff / MINUTE), "minute");
  if (diff < DAY) return rtf.format(-Math.floor(diff / HOUR), "hour");
  if (diff < 7 * DAY) return rtf.format(-Math.floor(diff / DAY), "day");
  return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}
