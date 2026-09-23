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
 * Outputs    : POST /api/groups, PUT /api/groups/{id} and
 *              PUT /api/groups/{id}/members. No module state — the caller
 *              (groups_dialog.js) owns dialogEl/fields/onSaved and decides
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
 * Save, as one call on add and two on edit.
 *
 * GroupUpdate carries no member_ids and set_members carries nothing else, so an
 * edit is a PUT of the group followed by a PUT of its membership. The second
 * only runs if the first succeeded: a half-applied save with the error still on
 * screen beats silently writing one of the two.
 */
export async function saveGroup(mode, editId, body) {
  if (mode !== "edit") {
    await api("/api/groups", jsonOpts("POST", body));
    return;
  }
  const { member_ids: memberIds, ...groupFields } = body;
  await api(`/api/groups/${editId}`, jsonOpts("PUT", groupFields));
  await api(`/api/groups/${editId}/members`, jsonOpts("PUT", { member_ids: memberIds }));
}
