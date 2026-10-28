/*
 * The Latest tab's two faces: the list, and one tracker in focus.
 *
 * Purpose    : Own the DOM skeleton inside #tab-latest (the list, and the focus
 *              view with its header and the borrowed day body) and draw the focus
 *              header: back "All" button, badge, name, Edit, and the two-way
 *              Story | Sightings switch.
 * Inputs     : The #tab-latest container; a device row; callbacks onBack, onEdit,
 *              onView(view) with view "story" | "raw".
 * Outputs    : structure(container) -> {list, focus, head, body}; drawFocus(),
 *              drawList().
 * Constraints: createElement/textContent only. The day body (#fp-day-host) is
 *              parked in `#fp-latest-focus-body` while focused and stays in the
 *              page (hidden) otherwise, because timeline.js addresses it by id.
 */
"use strict";

import { t } from "./i18n.js";
import { button } from "./components/button.js";
import { parkDayHost } from "./legacy_day_host.js";
import { editButton, rowBadge } from "./latest_rows.js";
import { trackerName } from "./latest_data.js";
import { displayName } from "./state.js";

function node(tag, id, cls) {
  const el = document.createElement(tag);
  if (id) el.id = id;
  if (cls) el.className = cls;
  return el;
}

/** Make sure the list and focus containers exist inside `container`; return them. */
export function structure(container) {
  let list = container.querySelector("#fp-latest-list");
  let focus = container.querySelector("#fp-latest-focus");
  if (!list) {
    list = node("div", "fp-latest-list", "fp-latest-list");
    focus = node("section", "fp-latest-focus", "fp-latest-focus");
    focus.hidden = true;
    focus.setAttribute("aria-label", t("latest.focusSwitchLabel"));
    focus.append(node("div", "fp-latest-focus-head", "fp-latest-focus-head"), node("div", "fp-latest-focus-body"));
    container.append(list, focus);
  }
  return { list, focus, head: focus.querySelector("#fp-latest-focus-head"), body: focus.querySelector("#fp-latest-focus-body") };
}

function switchButton(label, view, current, onView) {
  const btn = button({ label, size: "sm", variant: current === view ? "primary" : "secondary", attrs: { "data-view": view, "aria-pressed": String(current === view) } });
  btn.addEventListener("click", () => onView(view));
  return btn;
}

function viewSwitch(current, onView) {
  const wrap = node("div", null, "fp-latest-switch");
  wrap.setAttribute("role", "group");
  wrap.setAttribute("aria-label", t("latest.focusSwitchLabel"));
  wrap.append(switchButton(t("latest.focusStory"), "story", current, onView), switchButton(t("latest.focusSightings"), "raw", current, onView));
  return wrap;
}

function titleRow(device, { onBack, onEdit }) {
  const row = node("div", null, "fp-latest-focus-title");
  const back = button({ label: t("latest.focusBack"), icon: "chevron-left", size: "sm", title: t("latest.focusBackTitle"), onClick: onBack, id: "fp-focus-back" });
  const name = node("h2", "fp-focus-name", "fp-latest-focus-name");
  name.tabIndex = -1;
  name.textContent = trackerName(device);
  const edit = editButton(t("latest.editTracker", { name: name.textContent }), onEdit);
  row.append(back, rowBadge({ icon: device.icon, color: device.color, label: device.label, name: displayName(device) }, 28), name, edit);
  return row;
}

/** Show the focus view for `device` with `view` ("story" | "raw") selected; hide the list. */
export function drawFocus(container, device, view, handlers) {
  const { list, focus, head, body } = structure(container);
  list.hidden = true;
  focus.hidden = false;
  head.replaceChildren(titleRow(device, handlers), viewSwitch(view, handlers.onView));
  parkDayHost(body, view);
}

/** Show the list and hide the focus view (the day body stays parked, hidden). */
export function drawList(container) {
  const { list, focus, body } = structure(container);
  focus.hidden = true;
  list.hidden = false;
  parkDayHost(body, null);
}
