/*
 * "We found people in your trackers": the suggestions panel and its dashboard banner.
 *
 * Purpose    : Offer to group a person's trackers ("Sam Bag", "Sam Bike", ...)
 *              under one name, with every guess previewed and nothing applied
 *              until Accept. Used on the Groups tab, in the setup wizard's
 *              Groups step, and as a one-line banner on the dashboard.
 * Inputs     : GET /api/people/suggestions; POST /api/people/suggestions/accept.
 * Outputs    : Panel DOM inside the host; after an accept the Groups tab, the
 *              people list used for name links and the banner are refreshed.
 * Constraints: Never auto-applies. "Accept all" skips guesses that still need an
 *              answer (person or pet?) or that are low confidence. "Not now"
 *              hides the panel until a different set of suggestions appears.
 *              purge() empties every host (names must not survive a lock).
 */
"use strict";

import { plural, t } from "./i18n.js";
import { state } from "./state.js";
import { paneError } from "./pane_error.js";
import { acceptSuggestions, fetchPeople, fetchSuggestions } from "./person_api.js";
import { refreshPeopleCache } from "./person_links.js";
import { suggestionCard } from "./people_suggest_card.js";
import { unassignedSection } from "./people_suggest_unassigned.js";

const HIDE_KEY = "findplus.peopleHidden";
const hosts = new Map();
let banner = null;
let data = null;
let people = [];
let failure = null;
let busy = false;
let message = { text: "", kind: "" };

const sigOf = () => (data ? data.suggestions.map((s) => s.key).sort().join("|") : "");
const readHidden = () => { try { return localStorage.getItem(HIDE_KEY); } catch (_) { return null; } };
const writeHidden = (v) => { try { if (v === null) localStorage.removeItem(HIDE_KEY); else localStorage.setItem(HIDE_KEY, v); } catch (_) { /* private mode */ } };
const count = () => (data ? data.suggestions.length + data.unassigned.length : 0);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function pool() {
  const seen = new Map();
  [...data.suggestions.flatMap((s) => s.members), ...data.unassigned].forEach((m) => seen.set(m.device_id, m));
  return [...seen.values()];
}

async function apply(accept, dismiss = []) {
  if (busy) return;
  busy = true;
  message = { text: "", kind: "" };
  try {
    const out = await acceptSuggestions(accept, dismiss);
    const n = out.people.length;
    message = n ? { text: plural("people.panel.accepted", n, { n }), kind: "ok" } : { text: t("people.panel.dismissed"), kind: "ok" };
    await refreshPeopleCache();
    import("./groups.js").then((m) => m.loadGroups()).catch(() => {});
    hosts.forEach((h) => h.onChange && h.onChange());
  } catch (err) {
    if (err.message === "Locked") return;
    message = { text: t("people.panel.failed", { message: err.message }), kind: "err" };
  } finally {
    busy = false;
  }
  await load();
}

function acceptAll() {
  const ready = data.suggestions.filter((s) => !s.ask_kind && s.confidence !== "low");
  apply(ready.map((s) => ({ action: s.action, name: s.name, kind: s.kind || "person", group_id: s.group_id, members: s.members.map((m) => ({ device_id: m.device_id, role: m.role })) })));
}

function header(onHide) {
  const head = el("header", "ps-head");
  const h = el("h3", "ps-heading", t("people.panel.title"));
  h.id = "ps-title";
  head.appendChild(h);
  if (onHide) {
    const hide = el("button", "btn-secondary btn-tiny", t("people.panel.hide"));
    hide.type = "button";
    hide.addEventListener("click", () => { writeHidden(sigOf()); render(); });
    head.appendChild(hide);
  }
  return head;
}

function footer() {
  const row = el("div", "ps-foot");
  const ready = data.suggestions.filter((s) => !s.ask_kind && s.confidence !== "low").length;
  if (ready > 1) {
    const all = el("button", "btn btn-tiny ps-accept-all", t("people.panel.acceptAll", { n: ready }));
    all.type = "button"; all.addEventListener("click", acceptAll);
    row.appendChild(all);
  }
  const skipped = data.suggestions.length - ready;
  if (ready > 1 && skipped > 0) row.appendChild(el("span", "person-hint", plural("people.panel.acceptAllSkipped", skipped, { n: skipped })));
  row.appendChild(recheckButton());
  return row;
}

function recheckButton() {
  const b = el("button", "btn-secondary btn-tiny ps-recheck", t("people.panel.recheck"));
  b.type = "button";
  b.addEventListener("click", async () => { b.disabled = true; b.textContent = t("people.panel.rechecking"); await load(); });
  return b;
}

function fill(host, wizard) {
  const section = el("section", "ps-panel");
  section.setAttribute("aria-labelledby", "ps-title");
  if (failure) {
    host.replaceChildren(paneError({ title: t("people.panel.errorTitle"), message: failure.message, onRetry: () => load() }));
    return;
  }
  if (!data) { section.appendChild(el("p", "person-hint", t("people.panel.loading"))); host.replaceChildren(section); return; }
  const hidden = !wizard && count() > 0 && readHidden() === sigOf();
  if (count() === 0 || hidden) {
    section.classList.add("ps-compact");
    if (hidden) {
      const show = el("button", "btn-secondary btn-tiny", t("people.panel.show", { n: data.suggestions.length || data.unassigned.length }));
      show.type = "button"; show.addEventListener("click", () => { writeHidden(null); render(); });
      section.appendChild(show);
    } else section.appendChild(el("p", "person-hint", t("people.panel.empty")));
    section.appendChild(recheckButton());
    host.replaceChildren(section);
    return;
  }
  section.append(header(!wizard), el("p", "person-hint", t(wizard ? "people.panel.wizardLead" : "people.panel.lead")));
  const list = el("ul", "ps-list");
  const ctx = { onAccept: (body) => apply([body]), onDismiss: (key) => apply([], [key]) };
  data.suggestions.forEach((s) => list.appendChild(suggestionCard(s, pool(), ctx)));
  section.appendChild(list);
  const whose = unassignedSection(data.unassigned, people, ctx.onAccept);
  if (whose) section.appendChild(whose);
  const status = el("p", `ps-status${message.kind ? ` ps-status--${message.kind}` : ""}`, message.text);
  status.setAttribute("role", "status");
  section.append(status, footer());
  host.replaceChildren(section);
}

function renderBanner() {
  if (!banner) return;
  const n = data ? data.suggestions.length : 0;
  const hidden = n === 0 || readHidden() === sigOf();
  banner.hidden = hidden;
  if (hidden) { banner.replaceChildren(); return; }
  const text = el("span", "", plural("people.panel.banner", n, { n }));
  const review = el("button", "btn btn-tiny", t("people.panel.review"));
  review.type = "button";
  review.addEventListener("click", async () => {
    (await import("./main.js")).switchTab("groups");
    document.getElementById("fp-people-suggest")?.scrollIntoView({ block: "start" });
  });
  banner.replaceChildren(text, review);
}

function render() {
  hosts.forEach(({ wizard }, host) => fill(host, wizard));
  renderBanner();
}

/** Fetch the suggestions and the existing people, then redraw every host. */
export async function load() {
  if (state.locked) return;
  try {
    [data, people] = await Promise.all([fetchSuggestions(), fetchPeople()]);
    failure = null;
  } catch (err) {
    if (err.message === "Locked") return;
    failure = err;
  }
  render();
}

/** Show the panel inside `host` (the Groups tab, or the wizard step). */
export function mountSuggestions(host, { wizard = false, onChange = null } = {}) {
  hosts.set(host, { wizard, onChange });
  [...hosts.keys()].filter((h) => !h.isConnected).forEach((h) => hosts.delete(h));
  render();
  return load();
}

/** The dashboard's one-line banner host. */
export function mountBanner(host) {
  banner = host;
  renderBanner();
}

/** Lock purge: no name may survive. */
export function purge() {
  data = null; people = []; failure = null; message = { text: "", kind: "" };
  hosts.forEach((_, host) => host.replaceChildren());
  if (banner) { banner.replaceChildren(); banner.hidden = true; }
}
