/*
 * Groups tab: presence-panel rendering helpers.
 *
 * Purpose    : The map overlay circles/legend, the verdict wording and the
 *              together/diverged/stale name lists groups.js's selectGroup()
 *              and renderPresencePanel() draw from one
 *              GET /api/groups/{id}/presence response. Split out of
 *              groups.js at the PRI rule-7 300-line file cap (UAT4 N31
 *              follow-up added onGroupSaved()/isGroupSelected() there), the
 *              same way groups_dialog_dom.js came out of groups_dialog.js.
 * Inputs     : A GroupPresence response, its group (drawGroupOverlays' own
 *              colour) and a device-id/name -> member lookup (nameList).
 * Outputs    : DOM writes into the given overlay layer / legend element, and
 *              plain strings for the verdict badge and stale-row age.
 * Constraints: Every element is built with createElement/textContent, never
 *              raw markup assignment; esc() only guards a Leaflet tooltip,
 *              which does not go through the DOM the same way.
 *              renderPresencePanel() itself stays in groups.js (Playwright's
 *              test_groups.py dynamic-imports it from there); this module
 *              holds only the pieces that function does not need to keep.
 */
"use strict";

import { esc, fmtAgeMinutes } from "./state.js";
import { t } from "./i18n.js";

export function drawGroupOverlays(overlayLayer, presence, group) {
  overlayLayer.clearLayers();
  const legend = document.getElementById("fp-group-legend");
  if (legend) while (legend.firstChild) legend.removeChild(legend.firstChild);
  presence.members.forEach((member) => {
    if (member.status === "stale") return;
    if (member.latitude == null || member.longitude == null) return;
    L.circle([member.latitude, member.longitude], {
      radius: 80, color: group.color, fillOpacity: 0.2, weight: 1, keyboard: false,
    }).bindTooltip(esc(member.name)).addTo(overlayLayer);
    if (!legend) return;
    const item = document.createElement("span");
    item.className = "fp-legend-item";
    const swatch = document.createElement("span");
    swatch.className = "fp-legend-swatch";
    swatch.style.background = group.color;
    const label = document.createElement("span");
    label.textContent = member.name;
    item.append(swatch, label);
    legend.appendChild(item);
  });
}

/**
 * The phrase the API computed, with the old client-side rules as a fallback.
 *
 * The dashboard, the widget and the CLI each had their own mapping and printed
 * three different things for one state (E1 honesty round 3 F4), so the label is
 * served beside the verdict now. The fallback keeps an older daemon readable
 * and encodes the two rules that matter: `partial` with nobody diverged is not
 * divergence (round 2 F1), and `all_together` with a silent member is not the
 * whole group (round 3 F3).
 */
export function verdictLabel(presence) {
  const reporting = presence.reporting_count;
  const considered = presence.considered_count;
  const hasStaleMember = considered != null && reporting < considered;
  // N27: two reporting members can be genuinely far apart while a third has
  // no fix at all. The server's own verdict_label() still says "Diverged"
  // for that combination -- true about the reporting pair, but a confident
  // headline for a group Find+ only partly heard from (the body `note`
  // already names the stale member; the pill should not outrun it). The
  // all_together branch below already discloses the same gap inline
  // ("Together (2 of 3 reporting)"), so only the undisclosed, confident
  // "Diverged" needs the same downgrade, checked before trusting the
  // server's phrase.
  if (presence.verdict === "partial" && hasStaleMember && presence.diverged && presence.diverged.length > 0) {
    return t("groups.verdictPartial");
  }
  if (presence.verdict_label) return presence.verdict_label;
  if (presence.verdict === "all_together") {
    return considered && reporting < considered
      ? t("groups.verdictTogetherPartial", { reporting, considered })
      : t("groups.verdictTogether");
  }
  if (presence.verdict !== "partial") return t("groups.verdictUnknown");
  if (presence.diverged && presence.diverged.length > 0) return t("groups.verdictDiverged");
  return reporting === 1 ? t("groups.verdictOnlyOneReporting") : t("groups.verdictPartial");
}

/** U21: a plain-word explanation for the "Diverged" pill — empty for every
 * other verdict, so callers can always set it as a `title` unconditionally.
 * UAT7-N07: verdictLabel() above downgrades the pill text itself from
 * "Diverged" to "Partial" once a stale member makes "Diverged" an overclaim;
 * this must describe what the pill actually says, not what the raw diverged
 * flag alone would have said -- the same hasStaleMember condition, checked
 * the same way, decides which sentence applies. */
export function verdictTitle(presence) {
  if (presence.verdict !== "partial") return "";
  const reporting = presence.reporting_count;
  const considered = presence.considered_count;
  const hasStaleMember = considered != null && reporting < considered;
  const hasDiverged = presence.diverged && presence.diverged.length > 0;
  if (!hasDiverged) return "";
  return hasStaleMember ? t("groups.verdictPartialHint") : t("groups.verdictDivergedHint");
}

export function ageLabel(member) {
  return fmtAgeMinutes(member ? member.age_minutes : null);
}

// Ever reported at all? (UAT3 N19: "no fix yet" vs "no fix for {age}".)
export function hasEverReported(member) { return !!member && member.age_minutes != null; }

/**
 * A labelled list of member names.
 *
 * The together and diverged lists were two adjacent bare <ul>s with no
 * heading and no ::before, so nothing on screen said which was which -- only
 * the stale list described itself (honesty round 2 F11). An empty list renders
 * nothing at all rather than a heading over a void.
 */
export function nameList(id, heading, deviceIds, byId) {
  const wrap = document.createElement("div");
  if (!deviceIds || deviceIds.length === 0) return wrap;
  const title = document.createElement("p");
  title.className = "fp-list-heading";
  title.textContent = heading;
  wrap.appendChild(title);
  const ul = document.createElement("ul");
  ul.id = id;
  deviceIds.forEach((deviceId) => {
    const li = document.createElement("li");
    li.textContent = (byId.get(deviceId) || {}).name || deviceId;
    ul.appendChild(li);
  });
  wrap.appendChild(ul);
  return wrap;
}
