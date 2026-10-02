/*
 * "We noticed these places": the suggestion list for the Places tab and the wizard.
 *
 * Purpose    : Fetch GET /api/places/suggestions and show a card per likely place
 *              (Home first when an overnight spot exists), or say plainly when
 *              there is not enough history yet.
 * Inputs     : A host element and { onSaved(place), showEmpty: bool or () => bool } (say
 *              "not enough history" when there is nothing to suggest).
 * Outputs    : { refresh(), purge() }. A saved place is made by the card (POST
 *              /api/places); "Not a place" posts /api/places/suggestions/dismiss.
 * Constraints: createElement/textContent only. A failed fetch leaves the host
 *              empty (the tab is useful without it). While locked nothing is kept.
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";
import { suggestionCard } from "./places_noticed_card.js";

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

function clear(st) {
  st.cards.forEach((c) => c.destroy());
  st.cards = [];
  st.host.replaceChildren();
}

function emptyNote(st) {
  const wanted = typeof st.showEmpty === "function" ? st.showEmpty() : st.showEmpty;
  if (wanted) st.host.append(el("p", "fp-tab-hint pn-empty", t("places.noticed.notEnough")));
}

function paint(st, candidates) {
  clear(st);
  if (!candidates.length) {
    emptyNote(st);
    return;
  }
  const section = el("section", "pn-panel");
  section.setAttribute("aria-labelledby", "pn-heading");
  const heading = el("h3", "pn-heading", t("places.noticed.heading"));
  heading.id = "pn-heading";
  const list = el("ul", "pn-list");
  const handlers = { onSaved: (place) => saved(st, place), onDismiss: (c) => dismiss(st, c) };
  st.cards = candidates.map((c, i) => suggestionCard(c, String(i), handlers));
  st.cards.forEach((card) => list.append(card.li));
  section.append(heading, el("p", "fp-tab-hint", t("places.noticed.lead")), list);
  st.host.append(section);
  st.cards.forEach((card) => card.mount());
}

async function refresh(st) {
  let body;
  try {
    body = await api("/api/places/suggestions");
  } catch (_) {
    clear(st);
    return;
  }
  paint(st, body.candidates || []);
  if (st.note) st.host.prepend(Object.assign(el("p", "pn-saved", st.note), { role: "status" }));
}

async function dismiss(st, c) {
  try {
    await api("/api/places/suggestions/dismiss", {
      method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ latitude: c.lat, longitude: c.lon }),
    });
  } catch (err) {
    if (err.message === "Locked") return;
  }
  st.note = "";
  await refresh(st);
}

async function saved(st, place) {
  st.note = t("places.noticed.saved", { name: place.name });
  if (st.onSaved) await st.onSaved(place);
  await refresh(st);
}

export function mountNoticed(host, { onSaved, showEmpty = false }) {
  const st = { host, onSaved, showEmpty, cards: [], note: "" };
  return {
    refresh: () => refresh(st),
    purge: () => {
      st.note = "";
      clear(st);
    },
  };
}
