/*
 * Provider-derived chrome: what the dashboard calls the tracking side.
 *
 * Purpose    : Keep every provider-named string on screen true for the device
 *              set actually being tracked, and render each provider's footer
 *              honesty sentence only when a device of that kind is tracked.
 *              Split out of devices.js at the PRI rule-7 300-line file cap.
 * Inputs     : state.devices and state.config.notices.
 * Outputs    : The topbar poll tooltip, the observed-by card label, the
 *              Devices dialog heading and note, and the two footer notices.
 * Constraints: The footer sentences come verbatim from /api/config.notices,
 *              so honesty.py stays their single source. Provider names are
 *              trademarks and are never translated; only the neutral fallback
 *              wording is.
 */
"use strict";

import { $, state } from "./state.js";
import { t } from "./i18n.js";

/**
 * What to call the tracking side, derived from the tracked device set.
 *
 * Round 1 gated the footer honesty sentence and left the chrome around it
 * speaking only Google: an Apple-only user still read "Last observed by Find
 * Hub", "Devices on this Google account" and "about N Google requests per
 * hour" (E1 honesty round 2 F3). `network` names the tracking network,
 * `account` the account the devices hang off, `requests` the thing being
 * queried. A mixed or unknown set falls back to neutral wording rather than
 * picking a side.
 */
export function providerWording() {
  const providers = new Set(
    (state.devices || []).filter((d) => d.is_tracked !== false).map((d) => d.provider)
  );
  const apple = providers.has("apple-find-my");
  const other = [...providers].some((p) => p && p !== "apple-find-my");
  // The provider names are trademarks and stay as they are; only the neutral
  // fallback wording is prose a translator owns.
  if (apple && !other) return { network: "Find My", account: "Apple", requests: "Apple" };
  if (other && !apple) return { network: "Find Hub", account: "Google", requests: "Google" };
  return {
    network: t("devices.wordingProviders"),
    account: t("devices.wordingTracking"),
    requests: t("devices.wordingProviders"),
  };
}

/**
 * Rewrite the provider-named chrome for the current device set.
 *
 * These strings live in the markup because they are there before any device
 * list is loaded; this is the one place that keeps them true afterwards.
 */
export function syncProviderChrome() {
  const w = providerWording();
  const poll = $("btn-poll");
  if (poll) poll.title = t("devices.pollTitleFor", { requests: w.requests });
  const observed = $("card-observed-label");
  if (observed) observed.textContent = t("devices.cardObservedFor", { network: w.network });
  const heading = $("device-modal-title");
  if (heading) heading.textContent = t("devices.titleForAccount", { account: w.account });
  const note = $("device-modal-note");
  if (note) note.textContent = t("devices.noteForRequests", { requests: w.requests });
}

/**
 * Render each provider's footer sentence only when that provider is tracked.
 *
 * The footer used to render the Find Hub sentence unconditionally, so someone
 * tracking only AirTags read that their tags report "through Google Find Hub
 * network" (E1 honesty pass F1). Gating the Apple sentence alone left that
 * false sentence on screen, so both are device-derived now. Both come verbatim
 * from /api/config.notices, so honesty.py stays the single source.
 *
 * With no devices at all neither sentence renders: there is no history on
 * screen for either one to describe.
 */
export function syncProviderNotice() {
  const notices = state.config?.notices;
  setNotice($("apple-notice"), (d) => d.provider === "apple-find-my", notices?.apple);
  setNotice($("findhub-notice"), (d) => d.provider !== "apple-find-my", notices?.find_hub);
}

/** Show `text` on `el` when at least one tracked device matches `pred`. */
function setNotice(el, pred, text) {
  if (!el) return;
  const show = Boolean(text) && state.devices.some(pred);
  el.textContent = show ? text : "";
  el.hidden = !show;
}
