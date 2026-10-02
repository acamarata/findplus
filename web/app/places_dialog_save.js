/*
 * Place dialog: what gets sent when Save is pressed.
 *
 * Purpose    : Build the POST/PUT body from the dialog's fields (including the
 *              kind and, for a new place, the "tell me when anyone arrives or
 *              leaves" choice) and send it. Split out of places_dialog.js at the
 *              PRI rule-7 300-line file cap.
 * Inputs     : The open <dialog> and its `fields` (places_dialog_dom.js).
 * Outputs    : `{saved, editing}` from POST /api/places or PUT /api/places/{id};
 *              a new place's answer carries `notify_rule` (or null).
 * Constraints: A new place always says `notify` explicitly, so the server never
 *              guesses from a stale default. An edit never touches alert rules.
 */
"use strict";

import { api } from "./api.js";
import { radiusOf } from "./places_dialog_dom.js";
import { readNotify } from "./places_notify.js";

/** The fields every save sends. */
export function placeBody(fields) {
  return {
    name: fields.name.value,
    latitude: Number(fields.lat.value),
    longitude: Number(fields.lon.value),
    radius_meters: radiusOf(fields),
    color: fields.color.value,
    enter_confirmations: Number(fields.enter.value),
    exit_confirmations: Number(fields.exit.value),
    kind: fields.kind.select.value,
  };
}

/** Save the dialog's place; rejects with the API error for the caller to word. */
export async function submitPlace(dlg, fields) {
  const editing = dlg.dataset.mode === "edit";
  const body = editing ? placeBody(fields) : { ...placeBody(fields), ...readNotify(fields.notify) };
  const opts = { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const saved = editing
    ? await api(`/api/places/${dlg.dataset.editId}`, { ...opts, method: "PUT" })
    : await api("/api/places", { ...opts, method: "POST" });
  return { saved, editing };
}
