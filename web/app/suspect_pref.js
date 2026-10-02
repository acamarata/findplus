/*
 * The "Show sightings that look wrong" choice, shared by the dashboard and the
 * Person page. On by default; remembered in this browser only.
 */
"use strict";

import { t } from "./i18n.js";

const KEY = "findplus.showSuspect";

/** True unless the person switched it off. */
export function showSuspect() {
  try {
    return localStorage.getItem(KEY) !== "off";
  } catch (_) {
    return true;
  }
}

export function setShowSuspect(on) {
  try { localStorage.setItem(KEY, on ? "on" : "off"); } catch (_) { /* private mode */ }
}

/** The labelled checkbox. `onChange(on)` runs after the choice is stored. */
export function suspectToggle(id, onChange) {
  const label = document.createElement("label");
  label.className = "toggle suspect-toggle";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.id = id;
  box.checked = showSuspect();
  box.addEventListener("change", () => { setShowSuspect(box.checked); onChange(box.checked); });
  const span = document.createElement("span");
  span.textContent = t("quality.showSuspect");
  label.append(box, span);
  return label;
}
