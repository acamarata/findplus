/*
 * The Person page's day story: family lanes with the best-placed tracker first,
 * then one tracker's hour strip and list of stays and trips.
 *
 * Purpose    : Reuse the dashboard's own day-story pieces (trips_strip.js lanes
 *              and hour strip, trips_list.js rows) for a person. The lanes show
 *              every tracker side by side and never merge them; the list below
 *              belongs to the one tracker named in its heading.
 * Inputs     : A context {trackers, payloads, failed, day, focusId, selectedId,
 *              nameOf, onPick, onMember} from person_page.js.
 * Outputs    : One <section class="person-card person-story">.
 * Constraints: createElement/textContent only. A tracker whose day has not
 *              arrived shows "Loading", one that failed shows its own Retry.
 */
"use strict";

import { plural, t } from "./i18n.js";
import { buildItems, hasStory, summaryText } from "./trips_format.js";
import { hourStrip, lanes } from "./trips_strip.js";
import { storyList } from "./trips_list.js";

function heading(name) {
  const h = document.createElement("h3");
  h.className = "person-card-title";
  h.textContent = t("person.story.title", { name });
  return h;
}

function picker(ctx) {
  const wrap = document.createElement("div");
  wrap.className = "story-pick";
  const label = document.createElement("label");
  label.htmlFor = "person-story-pick";
  label.textContent = t("person.story.pick");
  const select = document.createElement("select");
  select.id = "person-story-pick";
  ctx.trackers.forEach((tr) => {
    const opt = document.createElement("option");
    opt.value = tr.device_id;
    opt.textContent = ctx.nameOf(tr.device_id);
    opt.selected = tr.device_id === ctx.focusId;
    select.appendChild(opt);
  });
  select.addEventListener("change", () => ctx.onMember(select.value));
  wrap.append(label, select);
  return wrap;
}

function note(cls, text) {
  const p = document.createElement("p");
  p.className = cls;
  p.textContent = text;
  return p;
}

function laneMembers(ctx) {
  return ctx.trackers.map((tr) => ({
    device_id: tr.device_id,
    name: ctx.nameOf(tr.device_id),
    payload: ctx.payloads.get(tr.device_id) || null,
    failed: ctx.failed.has(tr.device_id),
  }));
}

function trackerStory(ctx, payload) {
  const box = document.createElement("div");
  box.className = "person-story-one";
  if (!hasStory(payload)) {
    box.appendChild(note("story-summary", plural("trips.sparseLead", payload.fix_count, { n: payload.fix_count })));
    return box;
  }
  box.append(
    note("story-summary", summaryText(payload)),
    hourStrip(payload, ctx.day, ctx.onPick),
    storyList(buildItems(payload), payload, t("trips.listLabel"), ctx.onPick)
  );
  const n = payload.outliers.length;
  if (n) box.appendChild(note("story-stray", plural("trips.strays", n, { n })));
  return box;
}

/** The day story card. */
export function storyCard(ctx) {
  const section = document.createElement("section");
  section.className = "person-card person-story";
  section.append(heading(ctx.name));
  if (ctx.trackers.length > 1) {
    section.appendChild(lanes(laneMembers(ctx), ctx.day, ctx.focusId, { onMember: ctx.onMember, onRetry: ctx.onRetry }));
  }
  if (ctx.trackers.length > 1) section.appendChild(picker(ctx));
  const payload = ctx.payloads.get(ctx.focusId);
  if (payload) section.appendChild(trackerStory(ctx, payload));
  else section.appendChild(note("story-summary", ctx.failed.has(ctx.focusId) ? t("trips.laneFailed") : t("common.loading")));
  return section;
}
