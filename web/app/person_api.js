/*
 * The Person page's data: what to ask the local API, and what comes back.
 *
 * Purpose    : Fetch one person, their "now" sentence, the day summary, and one
 *              timeline per tracker, and turn the day summary into the shape the
 *              page draws. Every call is local; nothing here reaches a provider.
 * Inputs     : A person id and a local day (YYYY-MM-DD).
 * Outputs    : fetchPerson/fetchNow/fetchDay/fetchTimeline/sendDay, the
 *              left-behind and tracker calls, and normalizeDay(raw).
 * Constraints: The day summary (GET /api/people/{id}/day) is read defensively:
 *              a line is any object with text; every other field is optional.
 *              No coordinates are kept outside what the caller stores.
 */
"use strict";

import { api, postJson } from "./api.js";

const JSON_HEADERS = { "Content-Type": "application/json" };
const put = (path, body) => api(path, { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(body) });

export const fetchPerson = (id) => api(`/api/people/${id}`);
export const fetchNow = (id) => api(`/api/people/${id}/now`);
export const fetchDay = (id, date) => api(`/api/people/${id}/day?date=${date}`);
export const fetchTimeline = (id, date) => api(`/api/timeline?group_id=${id}&day=${date}`);
export const sendDay = (id, date) => postJson(`/api/people/${id}/day/send`, { date });
export const fetchLeftBehind = (id) => api(`/api/people/${id}/left-behind`);
export const dismissLeftBehind = (id, episode) => postJson(`/api/people/${id}/left-behind/${episode}/dismiss`, {});
export const saveTracker = (deviceId, body) => put(`/api/people/trackers/${deviceId}`, body);
export const fetchPeople = () => api("/api/people");

const first = (obj, keys) => {
  for (const k of keys) if (obj[k] !== undefined && obj[k] !== null) return obj[k];
  return null;
};

/** One summary line, whatever spelling of the optional fields the server used. */
function normalizeLine(raw, index) {
  const text = first(raw, ["text", "sentence", "label", "summary"]);
  if (!text) return null;
  return {
    id: first(raw, ["id"]) ?? `l${index}`,
    text: String(text),
    kind: first(raw, ["kind", "type"]) || "line",
    at: first(raw, ["at", "start_at", "observed_at", "time"]),
    endAt: first(raw, ["end_at"]),
    local: first(raw, ["local", "at_local", "start_local"]),
    evidence: first(raw, ["evidence", "device_ids"]) || [],
    confidence: first(raw, ["confidence"]),
    placeId: first(raw, ["place_id"]),
  };
}

/** The day summary as the page draws it. A missing field is an empty list, never an error. */
export function normalizeDay(raw) {
  const body = raw || {};
  const lines = (Array.isArray(body.lines) ? body.lines : []).map(normalizeLine).filter(Boolean);
  return {
    lines,
    leftBehind: Array.isArray(body.left_behind) ? body.left_behind : [],
    suspectCount: Number(body.suspect_count) || 0,
    gaps: Array.isArray(body.gaps) ? body.gaps : [],
    trackers: Array.isArray(body.trackers) ? body.trackers : [],
    label: body.label || "",
  };
}

/** What POST day/send said, as `{ok, channels, message}`. Anything but a clear failure reads as sent. */
export function sendResult(body) {
  const failed = body && (body.sent === false || body.ok === false || body.error);
  const channels = body && Array.isArray(body.channels) ? body.channels : [];
  return { ok: !failed, channels, message: (body && (body.error || body.detail)) || "" };
}
