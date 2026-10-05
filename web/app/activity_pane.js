/*
 * Activity pane adapter (All Activity tab).
 *
 * Purpose    : The mount point the Activity builder rewrites. TODAY it shows the
 *              old "Every sighting" list for the trackers the Show / Group
 *              filters allow, via legacy_day_host.js (same element Latest uses,
 *              moved here while this tab is open, switch and chips hidden).
 * Inputs     : mountActivity(container): container is #tab-activity. The day
 *              comes from state.day (the filter row's Day arrows drive it).
 * Outputs    : DOM inside the container.
 * Constraints (contract, see panel_tabs.js for the full text):
 *   - mountActivity(container) runs once at boot and again each time the tab
 *     is shown; idempotent. refreshActivity() runs on
 *     `findplus:data-refreshed` while visible (the legacy list redraws from
 *     loadDay(), so it has nothing to do today). When you replace this, stop
 *     calling attachDayHost() so the host goes back to Latest only.
 *   - Events you may listen to: findplus:data-refreshed, findplus:tab-changed,
 *     findplus:people-changed, findplus:accounts-changed.
 *   - The raw feed is rendered by track_blocks.js into #tracks; the new
 *     merged feed should read state.timeline / the /api endpoints it needs
 *     and render into the container it is given.
 */
"use strict";

import { attachDayHost } from "./legacy_day_host.js";

export function mountActivity(container) {
  attachDayHost(container, { activity: true });
}

export function refreshActivity() {
  /* The legacy list redraws from loadDay(); nothing extra to refresh. */
}
