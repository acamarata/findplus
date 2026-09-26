/*
 * Alert-rule dialog: which channels exist, and which are connected.
 *
 * Purpose    : availableChannels() answers whether native (desktop-app-only)
 *              is on the menu; connectedChannels() answers which of
 *              telegram/webhook/whatsapp have stored credentials, so the
 *              add/edit-rule dialog can disable the rest instead of letting a
 *              rule save against a channel that will only ever fail (UAT
 *              U11). channelLabels() is the one place every channel's label
 *              (and its "(not connected)" suffix) is resolved, so
 *              channel-picker.js can stay free of any i18n import.
 * Inputs     : window.__findplus_native (set only by the Tauri window, see
 *              alerts.js's widget-map toggle for the same check);
 *              GET /api/alerts/channels (gated).
 * Outputs    : BASE_CHANNELS, availableChannels(), connectedChannels(),
 *              channelLabels(connected).
 * Constraints: connectedChannels() is re-fetched every call -- credentials
 *              can be added or removed between dialog opens. A fetch failure
 *              resolves `null` ("unknown, disable nothing") rather than
 *              disabling every box.
 */
"use strict";
import { api } from "./api.js";
import { t } from "./i18n.js";

export const BASE_CHANNELS = ["telegram", "webhook", "whatsapp"];

/**
 * "native" (desktop notification) only when this page is actually running
 * inside the Tauri app window, never in a plain browser tab.
 *
 * UAT6 N05: this used to ask GET /api/version whether the platform string
 * started with "macOS" -- true on any Mac, including a developer's plain
 * Chrome/Safari tab pointed at the daemon, so "Desktop notification" showed
 * up (and, since native never needs credentials, defaulted to ticked) on a
 * surface that can never deliver it. window.__findplus_native is the one
 * flag the desktop shell actually sets (settings.js, settings_polling.js,
 * alerts.js's widget toggle all gate the same way); a plain tab never has it.
 */
export function availableChannels() {
  return Promise.resolve(
    window.__findplus_native === true ? [...BASE_CHANNELS, "native"] : BASE_CHANNELS,
  );
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
