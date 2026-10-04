/*
 * Groups tab: dialog-to-API save mapping.
 *
 * Purpose    : Turn the group dialog's field values into the POST/PUT bodies
 *              the API expects, and run the save call itself. Split out of
 *              groups_dialog.js at the PRI rule-7 300-line file cap (E13
 *              loop-1 follow-up), the same way groups_dialog_dom.js came out
 *              of it earlier.
 * Inputs     : The dialog's `fields` object (groups_dialog_dom.js's shape)
 *              for groupBody(); a save mode, an edit id and a body dict for
 *              saveGroup().
 * Outputs    : POST /api/groups and PUT /api/groups/{id} (members included).
 *              No module state — the caller (groups_dialog.js) owns dialogEl/fields/onSaved and decides
 *              what to do with a resolved or rejected save.
 * Constraints: groupBody() reads fields, never writes them. saveGroup() never
 *              catches: groups_dialog.js's onSave() is the single place that
 *              turns a rejection into UI (handleSaveError).
 */
"use strict";

import { api } from "./api.js";

export function groupBody(fields) {
  return {
    name: fields.name.value.trim(),
    icon: fields.icon.value,
    color: fields.color.value,
    quorum: fields.quorum.value === "custom" ? String(fields.quorumN.value) : fields.quorum.value,
    cluster_radius_meters: Number(fields.radius.value),
    stale_after_minutes: Number(fields.stale.value),
    member_ids: [...fields.members.querySelectorAll("input:checked")].map((c) => c.dataset.deviceId),
  };
}

function jsonOpts(method, body) {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/**
 * Save, as one call on add and one on edit.
 *
 * The edit PUT carries the member list too, so the server checks the quorum
 * against the members that will stand after the save (a quorum of 3 with one
 * member must not pass just because the members are written in a second call).
 */
export async function saveGroup(mode, editId, body) {
  if (mode !== "edit") {
    await api("/api/groups", jsonOpts("POST", body));
    return;
  }
  await api(`/api/groups/${editId}`, jsonOpts("PUT", body));
}
