/*
 * Poll status codes in plain words, and the in-app fix for each.
 *
 * Purpose    : /api/status and /api/poll-now report a poll's outcome as a
 *              code ("provider_unauthenticated", "timeout"). The dashboard
 *              printed those codes and the raw error text (UAT6-N06). This
 *              module is the one place that turns a code into a sentence,
 *              names the provider behind it, and says which in-app action
 *              fixes it.
 * Inputs     : A serialized poll run ({status, device_id}) and state.devices.
 * Outputs    : Catalog sentences and an action id ("signin" or null).
 * Constraints: Never shows error_message: it is a server-side exception
 *              string, not user copy. Provider names are trademarks and are
 *              not translated.
 */
"use strict";

import { state } from "./state.js";
import { t } from "./i18n.js";
import { api } from "./api.js";

/** Statuses that mean the poll itself worked, found a fix or not. */
const HEALTHY = new Set(["ok", "no_location"]);

/** Whether this run failed (a missing run is not a failure). */
export function isFailedPoll(run) {
  return Boolean(run) && !HEALTHY.has(run.status);
}

/** A few words for a card or a per-device result line. */
export function shortStatus(code) {
  switch (code) {
    case "ok": return t("pollStatus.ok");
    case "no_location": return t("pollStatus.noLocation");
    case "provider_unauthenticated":
    case "auth_error": return t("pollStatus.signedOut");
    case "provider_unavailable": return t("pollStatus.unavailable");
    case "timeout": return t("pollStatus.timeout");
    default: return t("pollStatus.failed");
  }
}

/** "Google Find Hub" / "Apple Find My" for the provider a run polled: the
 * run's own device when the API names it, else the one provider every
 * tracked device shares, else neutral wording rather than a guess. */
function providerNameFor(deviceId) {
  const devices = state.devices || [];
  const own = devices.find((d) => d.device_id === deviceId);
  const pool = own ? [own] : devices.filter((d) => d.is_tracked);
  const providers = new Set(pool.map((d) => d.provider || "google-find-hub"));
  if (providers.size !== 1) return t("pollStatus.anyProvider");
  return providers.has("apple-find-my") ? "Apple Find My" : "Google Find Hub";
}

/**
 * The banner sentence for a failed run, plus the action that fixes it.
 *
 * Returns {message, action}; action is "signin" when signing in is the fix
 * and null when the right move is to wait for the next poll.
 */
export function failedPollNotice(run) {
  const provider = providerNameFor(run.device_id);
  switch (run.status) {
    case "provider_unauthenticated":
    case "auth_error":
      return { message: t("pollStatus.bannerSignedOut", { provider }), action: "signin" };
    case "provider_unavailable":
      return { message: t("pollStatus.bannerUnavailable", { provider }), action: "signin" };
    case "timeout":
      return { message: t("pollStatus.bannerTimeout", { provider }), action: null };
    default:
      return { message: t("pollStatus.bannerFailed"), action: null };
  }
}

let signedInCache = null;

/**
 * Whether any provider account is signed in, cached for a minute so the
 * 45-second status refresh does not ask every time. A failed lookup, or one
 * made while locked, reads as "unknown" (null); callers then fall back to
 * the Devices action.
 */
export async function anyProviderSignedIn() {
  // Never from behind the lock: the purge re-renders the empty timeline, and
  // a 401 here would re-enter showLock() and purge again.
  if (state.locked) return null;
  if (signedInCache && Date.now() - signedInCache.at < 60000) return signedInCache.value;
  try {
    const { providers } = await api("/api/auth/status");
    const value = (providers || []).some((p) => p.signed_in);
    signedInCache = { at: Date.now(), value };
    return value;
  } catch (_) {
    return null;
  }
}

/** Open Settings on its Sign-in section, the in-app answer to "not signed in". */
export async function openSignin() {
  signedInCache = null;
  const settings = await import("./settings.js");
  await settings.openSettings();
  const section = document.getElementById("fp-settings-signin");
  if (section) section.scrollIntoView({ block: "start" });
}
