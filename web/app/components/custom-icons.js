/*
 * Custom icons: the "Your icons" section of the icon picker.
 *
 * Purpose    : Let a dialog upload a PNG and pick it as a device/group badge
 *              (icon id "custom:<16-hex>", specs/labels-and-icons.md custom
 *              icon amendment), alongside the pinned Lucide grid icon-picker.js
 *              already renders.
 * Inputs     : `host` to mount into and `onSelect(id)`, called when a custom
 *              swatch is clicked (mirrors icon-picker.js's own swatch click).
 * Outputs    : `{ section, refresh(), setPressed(id) }` — `section` is the
 *              DOM node appended into the picker root; the module owns
 *              everything inside it (upload, list, delete) from there.
 * Constraints: Unlike the pinned Lucide grid (which reads the sprite already
 *              in the DOM, no fetch), this list is per-installation and
 *              dynamic, so it fetches GET /api/icons/custom on mount and
 *              after every upload/delete. Every element is built with
 *              createElement/setAttribute, never raw markup. Every string is
 *              read through t() (icons.custom.* keys), never hardcoded.
 */
"use strict";

import { api } from "../api.js";
import { t } from "../i18n.js";

function iconIdShort(id) {
  return id.slice(7); // "custom:" is 7 characters
}

function statusParagraph() {
  const p = document.createElement("p");
  p.className = "fp-custom-icon-status";
  return p;
}

async function deleteCustomIcon(id, onDeleted, status) {
  if (!window.confirm(t("icons.custom.deleteConfirm"))) return;
  try {
    await api(`/api/icons/custom/${iconIdShort(id)}`, { method: "DELETE" });
    status.textContent = "";
    onDeleted();
  } catch (err) {
    if (err.message === "Locked") return;
    status.textContent = err.status === 409 ? t("icons.custom.deleteInUse") : err.message;
  }
}

/**
 * The small "x" delete button for a custom swatch.
 *
 * axe `nested-interactive` (2026-09-23): this used to live inside the
 * select button itself -- a button nested in a button, which assistive
 * tech cannot activate reliably. It is now a sibling of the select button,
 * both held by customSwatch()'s wrapper span, positioned into the same
 * top-right corner with `.fp-icon-swatch-wrap`/`.fp-icon-delete` in
 * components.css instead of DOM nesting.
 */
function deleteButton(id, onDeleted, status) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "fp-icon-delete";
  btn.setAttribute("aria-label", t("icons.custom.deleteIcon", { id: iconIdShort(id) }));
  btn.textContent = "×";
  btn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    deleteCustomIcon(id, onDeleted, status);
  });
  return btn;
}

/** The select button and its sibling delete button, held in one positioned
 * wrapper span so neither is nested inside the other. */
function customSwatch(id, current, onSelect, onDeleted, status) {
  const wrap = document.createElement("span");
  wrap.className = "fp-icon-swatch-wrap";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "fp-icon-swatch";
  btn.dataset.iconId = id;
  btn.setAttribute("aria-pressed", String(id === current));
  btn.setAttribute("aria-label", t("icons.custom.label"));
  const img = document.createElement("img");
  img.src = `/api/icons/custom/${iconIdShort(id)}.png`;
  img.alt = "";
  btn.appendChild(img);
  btn.addEventListener("click", () => onSelect(id));
  wrap.append(btn, deleteButton(id, onDeleted, status));
  return wrap;
}

async function uploadFile(file, status, onUploaded) {
  if (!file) {
    status.textContent = t("icons.custom.badFile");
    return;
  }
  const form = new FormData();
  form.set("file", file);
  try {
    const record = await api("/api/icons/custom", { method: "POST", body: form });
    status.textContent = "";
    onUploaded(record.id);
  } catch (err) {
    if (err.message === "Locked") return;
    status.textContent = t("icons.custom.uploadFailed", { message: err.message });
  }
}

/**
 * The file input row, wired to POST /api/icons/custom.
 *
 * UAT2 N10: a separate unstyled "Upload" button used to sit beside a raw
 * file input -- two steps for one action. Choosing a file now starts the
 * upload itself (there is nothing else to fill in first, unlike the Apple
 * accessory panel's name+file pair), and components.css styles the input's
 * own picker button (`::file-selector-button`) like `.btn-secondary`.
 */
function uploadRow(status, onUploaded) {
  const row = document.createElement("div");
  row.className = "fp-custom-icon-upload";
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/png";
  input.setAttribute("aria-label", t("icons.custom.upload"));
  input.addEventListener("change", () => {
    uploadFile(input.files[0], status, (id) => {
      input.value = "";
      onUploaded(id);
    });
  });
  row.append(input);
  return row;
}

/**
 * Build the "Your icons" section and its live handle.
 *
 * `value` is read once at build time; the picker's own `setValue()` (via the
 * returned `setPressed`) keeps it in sync afterward, the same split
 * icon-picker.js's own `applyPressedState` already uses.
 */
export function createCustomIconsSection(host, { value, onSelect }) {
  let current = value;
  const section = document.createElement("section");
  section.className = "fp-custom-icons";
  section.dataset.group = "custom";
  const heading = document.createElement("h4");
  heading.textContent = t("icons.custom.sectionLabel");
  const grid = document.createElement("div");
  grid.className = "fp-icon-grid";
  const status = statusParagraph();

  function select(id) {
    current = id;
    onSelect(id);
  }

  async function refresh() {
    let ids = [];
    try {
      ids = await api("/api/icons/custom");
    } catch (err) {
      if (err.message !== "Locked") status.textContent = err.message;
    }
    grid.innerHTML = "";
    for (const id of ids) grid.appendChild(customSwatch(id, current, select, refresh, status));
  }

  // Select first, then redraw: waiting for the list's own GET before
  // selecting left a window where Save sent the OLD icon (CI run
  // 35909159774). refresh() draws the new swatch already pressed.
  const upload = uploadRow(status, (id) => {
    select(id);
    refresh();
  });
  section.append(heading, grid, upload, status);
  host.appendChild(section);
  refresh();

  return {
    section,
    refresh,
    setPressed(id) {
      current = id;
      grid.querySelectorAll(".fp-icon-swatch").forEach((btn) => {
        btn.setAttribute("aria-pressed", String(btn.dataset.iconId === id));
      });
    },
  };
}
