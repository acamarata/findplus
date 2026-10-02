/*
 * Disconnect behind an inline confirm row (S11/WP8), for a sign-in card.
 *
 * Purpose    : The Disconnect button reveals "Disconnect <provider>?" with
 *              Disconnect / Cancel; confirming sends DELETE /api/auth/<id>.
 *              Never window.confirm, never a modal.
 * Inputs     : A flow with { card, deps, signedIn, settle() }, the provider id
 *              and an onError(message) callback.
 * Outputs    : { show(), hide() } wired to the card's buttons.
 * Constraints: textContent only (the error text comes from describeError()).
 */
"use strict";

import { describeError } from "./job_poller.js";

export function wireDisconnect(flow, providerId, onError) {
  const { disconnect, disconnectConfirm } = flow.card;
  const hide = () => {
    disconnectConfirm.row.hidden = true;
    disconnect.hidden = !flow.signedIn;
  };
  const show = () => {
    disconnectConfirm.row.hidden = false;
    disconnect.hidden = true;
    disconnectConfirm.confirm.focus();
  };
  const confirm = async () => {
    disconnectConfirm.confirm.disabled = true;
    try {
      await flow.deps.api(`/api/auth/${providerId}`, { method: "DELETE" });
      hide();
      await flow.settle();
    } catch (err) {
      hide();
      onError(describeError(err));
    } finally {
      disconnectConfirm.confirm.disabled = false;
    }
  };
  disconnect.addEventListener("click", show);
  disconnectConfirm.cancel.addEventListener("click", hide);
  disconnectConfirm.confirm.addEventListener("click", confirm);
  return { show, hide };
}
