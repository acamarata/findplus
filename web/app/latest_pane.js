/*
 * Latest pane adapter (the default side-panel tab).
 *
 * Purpose    : The mount point the Latest builder rewrites. TODAY it shows the
 *              old Dashboard body: the tracker blocks with the Day story /
 *              Every sighting switch, via legacy_day_host.js.
 * Inputs     : mountLatest(container): container is #tab-latest.
 * Outputs    : DOM inside the container.
 * Constraints (contract, see panel_tabs.js for the full text):
 *   - mountLatest(container) runs once at boot and again each time the tab is
 *     shown; it must be idempotent. refreshLatest() runs when
 *     `findplus:data-refreshed` fires while this tab is visible (today the
 *     day body redraws itself from loadDay(), so it has nothing to do).
 *   - Events you may listen to: findplus:data-refreshed, findplus:people-changed,
 *     findplus:accounts-changed, findplus:tab-changed.
 *   - Left-behind chips (#fp-left-behind) and the people banner
 *     (#fp-people-banner) live in the legacy body; main.js mounts them there.
 *   - A tracker or person row should call switchTab / set the hash
 *     (#/tracker/<id>, #/person/<id>) rather than touching other panes.
 */
"use strict";

import { attachDayHost } from "./legacy_day_host.js";

export function mountLatest(container) {
  attachDayHost(container, { activity: false });
}

export function refreshLatest() {
  /* The legacy body redraws from loadDay(); nothing extra to refresh. */
}
