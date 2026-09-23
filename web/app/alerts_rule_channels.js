/*
 * Alert-rule dialog: which channels exist, and which are connected.
 *
 * Purpose    : availableChannels() answers whether native (macOS-only) is on
 *              the menu; connectedChannels() answers which of
 *              telegram/webhook/whatsapp have stored credentials, so the
 *              add/edit-rule dialog can disable the rest instead of letting a
 *              rule save against a channel that will only ever fail (UAT
 *              U11). channelLabels() is the one place every channel's label
 *              (and its "(not connected)" suffix) is resolved, so
 *              channel-picker.js can stay free of any i18n import.
 * Inputs     : GET /api/version (public, never trips the lock screen);
 *              GET /api/alerts/channels (gated).
 * Outputs    : BASE_CHANNELS, availableChannels(), connectedChannels(),
 *              channelLabels(connected).
 * Constraints: availableChannels() is memoized for the session (the platform
 *              never changes mid-session); connectedChannels() is NOT --
 *              credentials can be added or removed between dialog opens, so
 *              it is re-fetched every call. A fetch failure resolves `null`
 *              ("unknown, disable nothing") rather than disabling every box.
 */
"use strict";
import { api } from "./api.js";
import { t } from "./i18n.js";

export const BASE_CHANNELS = ["telegram", "webhook", "whatsapp"];

let availableChannelsPromise = null;
export function availableChannels() {
  availableChannelsPromise ||= fetch("/api/version")
    .then((r) => (r.ok ? r.json() : {}))
    .then((version) =>
      typeof version.platform === "string" && version.platform.startsWith("macOS")
        ? [...BASE_CHANNELS, "native"]
        : BASE_CHANNELS,
    )
    .catch(() => BASE_CHANNELS);
  return availableChannelsPromise;
}

/** Set<channel id> of telegram/webhook/whatsapp with stored credentials, or
 *  null on any fetch failure. */
export async function connectedChannels() {
  try {
    const ch = await api("/api/alerts/channels");
    return new Set(BASE_CHANNELS.filter((id) => ch[id] && ch[id].configured));
  } catch (_) {
    return null;
  }
}

/** `connected` is a Set (from connectedChannels()) or null for "unknown, mark
 *  nothing"; native has no credential concept, so it is always "connected". */
export function channelLabels(connected) {
  return Object.fromEntries(
    [...BASE_CHANNELS, "native"].map((id) => {
      const label = t("alerts.channels." + id);
      const isConnected = connected === null || id === "native" || connected.has(id);
      return [id, isConnected ? label : t("alerts.channelNotConnected", { channel: label })];
    }),
  );
}
