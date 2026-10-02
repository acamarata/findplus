/*
 * Day story helpers: clock text, wording and the ordered story items.
 *
 * Purpose    : Turn one /api/trips answer into the rows the day story shows
 *              (stays, trips and gap markers in time order) and the plain
 *              sentences that describe them. Pure: no DOM, no network.
 * Inputs     : The /api/trips body for one tracker and one day.
 * Outputs    : buildItems(payload), titleOf(item), metaOf(item), clockOf(iso),
 *              minuteOfDay(iso, day), TRIP_COLORS and placeColor(name).
 * Constraints: Times are read from the server's own local ISO strings
 *              (`*_local`), never converted to this browser's zone, so a day
 *              reads the same wherever the page is opened. Distances are always
 *              called approximate, as the API says.
 */
"use strict";

import { fmtDuration, fmtDistance } from "./state.js";
import { plural, t } from "./i18n.js";

/** One colour per trip, none of them a tracker colour or the grey of a stay. */
export const TRIP_COLORS = ["#d9480f", "#7048e8", "#0b7285", "#c2255c", "#2b8a3e", "#b5740a"];
/** Stays are one calm slate; place colours in the family lanes use this family too. */
export const STAY_COLOR = "#51627a";
const PLACE_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#14b8a6"];
const UNNAMED_COLOR = "#94a3b8";

/** "7:42 AM" from the server-local ISO text, in this browser's locale. */
export function clockOf(iso) {
  if (!iso) return "";
  return new Date(2000, 0, 1, Number(iso.slice(11, 13)), Number(iso.slice(14, 16))).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Minutes after local midnight of `day` (YYYY-MM-DD), clamped to the day. */
export function minuteOfDay(iso, day) {
  const date = iso.slice(0, 10);
  if (date < day) return 0;
  if (date > day) return 1440;
  return Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16)) + Number(iso.slice(17, 19) || 0) / 60;
}

/**
 * The times a row is worded with. A trip's own range is its first to last
 * sighting ON THE MOVE: the sightings at either end belong to the stays on
 * both sides, so "left Home at 7:35" would claim more than a tag that was only
 * seen again at 7:42. A trip with no moving sighting keeps its whole window.
 */
export function windowOf(item) {
  const pts = item.points || [];
  if (item.kind !== "trip" || !item.fix_count || pts.length < 2) return item;
  const first = pts[item.from ? 1 : 0];
  const last = pts[pts.length - (item.to ? 2 : 1)];
  const minutes = (Date.parse(last.at) - Date.parse(first.at)) / 60000;
  return { start_local: first.local, end_local: last.local, duration_minutes: Math.max(minutes, 0) };
}

export function rangeText(item) {
  const w = windowOf(item);
  if (clockOf(w.start_local) === clockOf(w.end_local)) return clockOf(w.start_local);
  return t("trips.range", { from: clockOf(w.start_local), to: clockOf(w.end_local) });
}
export const sightingsText = (n) => plural("trips.sightings", n, { n });
const minutesText = (m) => fmtDuration(Math.round(m) * 60);

/** A saved place's name, or null for a stop nobody named. */
const namedEnd = (end) => (end && end.place_id != null ? end.label : null);

/** "Trip to School", "Trip from Home", "Trip to an unnamed stop", or just "Trip". */
function tripTitle(trip) {
  const [to, from] = [trip.to, trip.from];
  if (to) return namedEnd(to) ? t("trips.tripTo", { place: to.label }) : t("trips.tripToUnnamed");
  if (from) return namedEnd(from) ? t("trips.tripFrom", { place: from.label }) : t("trips.tripFromUnnamed");
  return t("trips.tripPlain");
}

export function titleOf(item) {
  if (item.kind === "trip") return tripTitle(item);
  if (item.kind === "gap") return t("trips.gapTitle", { from: clockOf(item.start_local), to: clockOf(item.end_local) });
  return item.place_id != null ? item.label : t("trips.unnamedStop");
}

/** The grey line under a row's title. */
export function metaOf(item) {
  if (item.kind === "gap") return `(${minutesText(item.minutes)})`;
  const minutes = windowOf(item).duration_minutes;
  const parts = minutes >= 1 ? [minutesText(minutes)] : [];
  if (item.kind === "trip") {
    parts.push(t("trips.aboutDistance", { distance: fmtDistance(item.distance_meters) }));
    parts.push(item.fix_count ? sightingsText(item.fix_count) : t("trips.noSightingsAlong"));
    if (!item.to) parts.push(t("trips.noStopReached"));
  } else {
    parts.push(sightingsText(item.fix_count));
  }
  return parts.join(" · ");
}

/** An extra quiet-time sentence, or "" when there is nothing worth saying. */
export function quietOf(item, gaps) {
  if (item.kind === "stay" && item.longest_gap_minutes > 60) {
    return t("trips.stayQuiet", { duration: minutesText(item.longest_gap_minutes) });
  }
  if (item.kind === "trip" && item.fix_count) {
    const inner = gaps.find((g) => g.inside === item.id);
    return inner ? t("trips.gapTitle", { from: clockOf(inner.start_local), to: clockOf(inner.end_local) }) : "";
  }
  return "";
}

/** Stays, trips and free-standing gaps, oldest first. A stay sorts before a trip that starts with it. */
export function buildItems(payload) {
  const rank = { stay: 0, trip: 1, gap: 2 };
  const stays = payload.stays.map((s) => ({ ...s, kind: "stay" }));
  const trips = payload.trips.map((x, i) => ({ ...x, kind: "trip", colorIndex: i % TRIP_COLORS.length }));
  const gaps = payload.gaps.filter((g) => g.inside == null).map((g, i) => ({ ...g, kind: "gap", id: `g${i}` }));
  return [...stays, ...trips, ...gaps].sort(
    (a, b) => a.start_at.localeCompare(b.start_at) || rank[a.kind] - rank[b.kind]
  );
}

/** Is there a story to tell, or only scattered sightings? */
export const hasStory = (payload) => payload.trips.length > 0 || payload.stays.some((s) => s.fix_count > 1);

/** A steady colour per place name, grey for unnamed stops. */
export function placeColor(item) {
  if (item.place_id == null) return UNNAMED_COLOR;
  let hash = 0;
  for (const ch of String(item.place_id)) hash = (hash * 31 + ch.charCodeAt(0)) % 9973;
  return PLACE_COLORS[hash % PLACE_COLORS.length];
}

/** One sentence for the top of the list: how many sightings became how many rows. */
export function summaryText(payload) {
  return t("trips.summary", {
    sightings: sightingsText(payload.fix_count),
    stays: plural("trips.stays", payload.stays.length, { n: payload.stays.length }),
    trips: plural("trips.trips", payload.trips.length, { n: payload.trips.length }),
  });
}
