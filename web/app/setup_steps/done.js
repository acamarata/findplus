/*
 * Onboarding step 8 — Done.
 *
 * Purpose    : Say what the session set up, and nothing else
 *              (specs/onboarding.md § 4 row 8).
 * Inputs     : GET /api/devices' own tracked_count (the same figure the
 *              dashboard widget uses) and GET /api/auth/status.
 * Outputs    : DOM inside the step container.
 * Constraints: Display only, and deliberately without an onNext: the Wizard's
 *              own Done button is the single writer of
 *              `onboarding.completed_at` from inside the wizard.
 *              UAT4 N29: this used to filter ctx.state.devices, which is only
 *              ever populated by the Devices step actually running this
 *              session (onEnter/onNext there). A reload that resumed setup
 *              past that step, or a Devices step the user skipped, left it
 *              `[]` and showed "0 devices tracked" over six real tracked
 *              devices. The server's own count is never stale this way.
 *              CI flake fix (2026-09-25): render() paints the heading before
 *              onEnter's fetch settles (wizard.js fires onEnter without
 *              awaiting it, on purpose, so a slow re-fetch cannot hold up the
 *              chrome). The summary paragraph carries data-ready="false"
 *              until the count actually lands, so nothing -- a screen reader
 *              or a test -- reads "You're set up" as a signal that the count
 *              underneath it is final.
 *              UAT6-N19: "You're set up · 0 devices tracked" with nobody
 *              signed in and nothing tracked read as a success, when it is
 *              exactly the state that needs fixing. That combination (both
 *              empty, not just a deliberate 0) now swaps the heading and
 *              summary for a plain "nothing connected yet" pair and offers a
 *              button straight back to Sign-in, instead of celebrating.
 */
"use strict";

import { plural, t } from "../i18n.js";

/** The live step's elements, replaced on every render. */
let els = null;

function renderComplete(trackedCount) {
  els.heading.textContent = t("setup.done.title");
  els.summary.textContent = plural("setup.done.summary", trackedCount, { n: trackedCount });
  els.signinBtn.hidden = true;
  els.facts.hidden = false;
}

function renderIncomplete() {
  els.heading.textContent = t("setup.done.incomplete_title");
  els.summary.textContent = t("setup.done.incomplete_summary");
  els.signinBtn.hidden = false;
  els.facts.hidden = true;
}

function item(text) {
  const li = document.createElement("li");
  li.textContent = text;
  return li;
}

/** Where things live: the menu bar on the desktop app, the address otherwise. */
function whereList() {
  const list = document.createElement("ul");
  list.className = "fp-wizard-points";
  list.append(
    item(
      window.__findplus_native === true
        ? t("setup.done.where_native")
        : t("setup.done.where_web", { url: window.location.origin })
    ),
    item(t("setup.done.where_settings"))
  );
  return list;
}

/** "8 people, 1 group." People and pets are not groups; say each plainly. */
function peopleAndGroups(all) {
  const people = all.filter((g) => g.kind === "person" || g.kind === "pet").length;
  const groups = all.length - people;
  if (!people) return plural("setup.done.groups", groups, { n: groups });
  const parts = [plural("setup.done.peopleCount", people, { n: people })];
  if (groups) parts.push(plural("setup.done.groupsCount", groups, { n: groups }));
  return `${parts.join(", ")}.`;
}

/** What Find+ is doing right now, from the server's own numbers. */
function paintFacts(accounts, tracked, extras) {
  const [settings, groups, places, lock] = extras.map((r) => (r.status === "fulfilled" ? r.value : null));
  els.facts.textContent = "";
  els.facts.append(
    item(accounts.length ? t("setup.signin.signed_in_as", { accounts: accounts.join(", ") }) : t("setup.done.no_account"))
  );
  const minutes = settings && settings["poll.interval_minutes"];
  if (!tracked) els.facts.append(item(t("setup.done.not_polling")));
  else if (minutes) els.facts.append(item(t("setup.done.polling", { n: minutes })));
  if (groups) els.facts.append(item(peopleAndGroups(groups)));
  if (places) els.facts.append(item(plural("setup.done.places", places.length, { n: places.length })));
  if (lock) els.facts.append(item(t(lock.lock_configured ? "setup.done.lock_on" : "setup.done.lock_off")));
}

export default {
  id: "done",
  canSkip: false,
  render(container, ctx) {
    container.textContent = "";
    const heading = document.createElement("h2");
    heading.textContent = t("setup.done.title");
    const summary = document.createElement("p");
    summary.setAttribute("aria-live", "polite");
    summary.dataset.ready = "false";
    const facts = document.createElement("ul");
    facts.id = "fp-setup-done-facts";
    facts.className = "fp-wizard-points";
    facts.hidden = true;
    const signinBtn = document.createElement("button");
    signinBtn.type = "button";
    signinBtn.id = "fp-setup-done-signin";
    signinBtn.className = "btn btn-secondary";
    signinBtn.textContent = t("setup.done.go_to_signin");
    signinBtn.hidden = true;
    signinBtn.addEventListener("click", () => ctx.goToStep("signin"));
    const whereHead = document.createElement("h3");
    whereHead.textContent = t("setup.done.where_title");
    els = { heading, summary, signinBtn, facts };
    container.append(heading, summary, facts, signinBtn, whereHead, whereList());
  },
  async onEnter(ctx) {
    const [{ tracked_count: trackedCount }, authStatus, ...extras] = await Promise.all([
      ctx.api("/api/devices"),
      ctx.api("/api/auth/status"),
      // Nice to have: a failure here drops that line, never the summary.
      ...["/api/settings", "/api/groups", "/api/places", "/api/lock/status"].map((url) =>
        ctx.api(url).then((v) => ({ status: "fulfilled", value: v }), () => ({ status: "rejected" }))
      ),
    ]);
    const signedIn = (authStatus.providers || []).filter((p) => p.signed_in);
    if (signedIn.length || trackedCount) {
      paintFacts(signedIn.map((p) => p.account || p.id), trackedCount, extras);
      renderComplete(trackedCount);
    } else renderIncomplete();
    // Set last, after either branch has painted its own final text: this is
    // what tells a reader (or a test) the async fetch has actually landed.
    els.summary.dataset.ready = "true";
  },
};
