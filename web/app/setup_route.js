/*
 * The #/setup route: opening the wizard, leaving it, and the resume banner.
 *
 * Purpose    : Everything main.js needs to know about onboarding, kept out of
 *              main.js so that file stays inside PRI rule 7's 300-line cap.
 * Inputs     : GET /api/settings (the two onboarding.* fields), the catalog.
 * Outputs    : #setup-view mounted or torn down, #app-shell hidden or shown,
 *              the #setup-banner bar under the topbar.
 * Constraints: The only writer of onboarding.* here is the Wizard itself.
 *              Nothing in this file stamps completed_at: entering and leaving
 *              the route must never look like finishing setup
 *              (specs/onboarding.md § 5).
 */
"use strict";

import { $, state } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";

/** Per-tab, per-load: a reload must show the setup banner again. */
const BANNER_DISMISSED_KEY = "findplus.setupBannerDismissed";

/**
 * Mount the onboarding wizard as a full view in place of the dashboard.
 *
 * `#/setup` is not a dialog, so closeModals() has nothing to do with it: the
 * shell is hidden outright and closeSetupRoute() brings it back.
 */
export async function openSetupRoute() {
  $("app-shell").classList.add("hidden");
  // On a first launch the wizard opens INSTEAD of bootDashboard(), so nothing
  // has loaded /api/config yet. Four steps read their honesty sentence off
  // state.config.notices, and a blank sentence is exactly the failure PRI rule
  // 4 exists to stop.
  if (!state.config) {
    const main = await import("./main.js");
    await main.loadConfig();
  }
  const { mountSetup } = await import("./setup.js");
  const settings = await api("/api/settings");
  await mountSetup(resumePoint(settings));
}

/**
 * Where a fresh mount starts.
 *
 * `onboarding.last_step` is the resume point of an UNFINISHED setup, which is
 * what the banner's "Resume setup" link is for. Once Done has run it holds
 * "done", so honouring it on a re-entry would open Settings' "Run setup again"
 * on the summary screen with nothing left to do. A re-run starts at step 1.
 */
function resumePoint(settings) {
  return settings["onboarding.completed_at"] === null ? settings["onboarding.last_step"] : null;
}

/**
 * Leave the wizard when the hash moves off `#/setup`.
 *
 * Without this the route could be entered but never left: browser Back, or the
 * Notifications step's "configure later" link, changed the hash and left the
 * wizard mounted over a hidden shell.
 */
export async function closeSetupRoute() {
  if (!$("setup-view").firstChild) return;
  const { closeSetup } = await import("./setup.js");
  closeSetup();
}

/**
 * The "setup isn't finished" bar, shown when the wizard was not forced.
 *
 * Dismissal is `sessionStorage`, never `localStorage` and never server-side: a
 * fresh load shows it again until `onboarding.completed_at` is actually set.
 * Idempotent, so a second call cannot stack a second bar.
 */
export function showSetupBanner() {
  if ($("setup-banner")) return;
  try {
    if (sessionStorage.getItem(BANNER_DISMISSED_KEY) === "1") return;
  } catch (_) { /* private mode: show the banner rather than hide it */ }

  const banner = document.createElement("div");
  banner.id = "setup-banner";
  banner.setAttribute("role", "status");
  const text = document.createElement("span");
  text.textContent = t("setup.banner.unfinished");
  const resume = document.createElement("a");
  resume.href = "#/setup";
  resume.textContent = t("setup.banner.resume");
  const dismiss = document.createElement("button");
  dismiss.type = "button";
  dismiss.className = "btn btn-tiny";
  dismiss.textContent = t("setup.banner.dismiss");
  dismiss.addEventListener("click", () => {
    try {
      sessionStorage.setItem(BANNER_DISMISSED_KEY, "1");
    } catch (_) { /* nothing to remember it with; hiding it is still right */ }
    banner.remove();
  });

  banner.append(text, resume, dismiss);
  // Under the toolbar, which is what the wiki and specs/onboarding.md § 5 both
  // describe; as the shell's first child it sat above the brand instead.
  const shell = $("app-shell");
  const topbar = shell.querySelector(".topbar");
  shell.insertBefore(banner, topbar ? topbar.nextSibling : shell.firstChild);
}

/**
 * Redirect to the wizard on a first run, or offer it in a banner.
 *
 * A 401 means the app is locked, which only happens once a PIN exists, which
 * implies a wizard that already ran: the lock screen takes over and this check
 * does nothing. Any other failure is a real error and is not swallowed.
 */
export async function checkOnboarding() {
  const settings = await api("/api/settings").catch((err) =>
    err.status === 401 ? null : Promise.reject(err)
  );
  if (settings && settings["onboarding.completed_at"] === null) {
    if (!window.location.hash) {
      window.location.hash = "#/setup";
      return true;
    }
    showSetupBanner();
  }
  return false;
}
