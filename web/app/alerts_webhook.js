/*
 * Alerts tab: the webhook channel section (URL + secret, Save/Remove).
 * Split out of alerts_channels.js at the PRI rule-7 300-line file cap
 * (UAT6 N02/N16 widened it past the limit, matching the earlier
 * alerts_telegram_targets.js split).
 *
 * Purpose    : Render the webhook URL/secret fields and their Save/Remove
 *              round trips, without ever putting the server's masked URL
 *              into the editable field (UAT6 N02, blocking: Save on an
 *              unchanged field used to write the literal masked string back
 *              as the real URL) or silently clobbering a saved secret on
 *              every unrelated save (same finding, "webhook secret").
 * Inputs     : GET/PUT/DELETE /api/alerts/channels/webhook.
 * Outputs    : DOM under #fp-webhook-section; re-exported for
 *              alerts_channels.js (loadChannels/wireChannelControls/purge).
 * Constraints: Never renders the field over what someone is mid-typing (same
 *              guard alerts_telegram_targets.js's renderTelegramTargets()
 *              uses). saveWebhook()/removeWebhook() take the caller's own
 *              reload function rather than importing loadChannels from
 *              alerts_channels.js, which would import this module back --
 *              never a circular import between the two.
 */
"use strict";
import { $ } from "./state.js";
import { t } from "./i18n.js";
import { api } from "./api.js";
import { mappedError } from "./alerts_channel_errors.js";

/** UAT6 N16: routes_alerts_channels.py's put_webhook() 422 details are raw
 *  English -- mapped to a catalog sentence the same way Telegram's own
 *  bot-token error already is (alerts_channels.js's VALIDATION_DETAIL_KEYS). */
const WEBHOOK_VALIDATION_KEYS = {
  "url must be https or http loopback": "alerts.invalidWebhookUrl",
  "url must not repeat the masked placeholder": "alerts.webhookMaskedUrl",
};

/** UAT6 N02: the two shapes channels_response()'s mask_url() sends back for
 *  a configured webhook ("http://host/…1234", the common case, or a bare/
 *  short-tail "http://host/***"). Neither is a value the PUT should accept
 *  -- checked client-side here as an early, friendly refusal;
 *  routes_alerts_channels.py's put_webhook() refuses the same shapes
 *  server-side too, so a direct API call gets the same guarantee. */
const MASK_MARKERS = ["***", "…"];

/** Shows `text` in `el`, or hides `el` when `text` is falsy (mirrors
 *  alerts_channels.js's own helper of the same name -- three lines, not
 *  worth a third module to share). */
function setVisibleText(el, text) {
  el.textContent = text || "";
  el.classList.toggle("hidden", !text);
}

/** Whether the last render saw a configured webhook -- saveWebhook() reads
 *  this to know whether an empty URL field means "nothing saved yet"
 *  (refuse) or "keep the current one" (omit from the PUT body). Module
 *  state, not a DOM read: the field itself never carries the real URL. */
let webhookConfigured = false;

/**
 * The webhook URL field only, never on top of what someone is mid-typing.
 *
 * init()'s boot-time refreshAll() (alerts.js) fires loadChannels() without
 * awaiting it; on a slow daemon that GET can still be in flight when a test
 * or a real user fills #fp-webhook-url and clicks Save. Unconditionally
 * overwriting the field here raced that fill and won intermittently under
 * load (E13 loop3 L3-1, CI 35558... webhook_save: "zero PUT requests reached
 * the server" -- saveWebhook()'s own guard fired because this stale render
 * had just cleared the field the click was about to read). Skipping the
 * write while the field is focused closes the gap: the moment loadChannels()
 * runs again (saveWebhook()'s own reload, or the next tab open), focus has
 * moved on and the real server value renders as before.
 *
 * UAT6 N02 (blocking): this used to put channels_response()'s MASKED url
 * straight into the value -- an editable field holding a value the server
 * would refuse, and if Save was pressed unchanged, the literal masked
 * string got written back as the real URL (verified in alerts.json),
 * breaking the webhook silently. The field is never prefilled with it now:
 * the masked value only ever appears as the "Current:" text
 * (renderWebhookSection) and, so it reads as "saved", as this field's own
 * placeholder. An empty field plus Save means "keep the current URL"
 * (saveWebhook()); `required` flips on only once nothing is saved yet, so
 * Save on a truly empty field still gets a native "fill this in" message
 * instead of silently no-op'ing.
 */
function renderWebhookUrl(webhook) {
  const el = $("fp-webhook-url");
  webhookConfigured = !!webhook.configured;
  el.required = !webhookConfigured;
  if (document.activeElement === el) return;
  el.value = "";
  el.placeholder = webhookConfigured
    ? t("alerts.webhookCurrent", { url: webhook.url })
    : t("alerts.urlPlaceholder");
}

export function renderWebhookSection(webhook) {
  renderWebhookUrl(webhook);
  setVisibleText(
    $("fp-webhook-current"),
    webhook.configured &&
      t("alerts.webhookCurrent", { url: webhook.url }) +
        (webhook.has_secret ? t("alerts.webhookSecretSet") : ""),
  );
}

/**
 * UAT6 N02/N16: url/secret are both omitted from the PUT body (not sent as
 * "" or null) when the field is left blank -- routes_alerts_channels.py's
 * put_webhook() reads an omitted field as "keep whatever is already saved",
 * never as "clear it". Before this, an untouched (always-blank) secret
 * field re-saved on every URL-only edit silently wiped a working secret;
 * now leaving either field blank changes nothing about it. There is no way
 * left in this form to blank the secret alone -- Remove clears the whole
 * channel, same as before. `reload` is alerts_channels.js's loadChannels,
 * passed in rather than imported (see this module's own docstring).
 */
export async function saveWebhook(reload) {
  const urlEl = $("fp-webhook-url");
  const statusEl = $("fp-webhook-status");
  statusEl.textContent = "";
  const url = urlEl.value.trim();
  // The mask marker can only land here by accident (a paste, or a focus-guard
  // miss) since the field is never prefilled with it (renderWebhookUrl()
  // above) -- caught before the round trip so the message names the actual
  // mistake instead of a generic "invalid URL".
  if (MASK_MARKERS.some((marker) => url.includes(marker))) {
    statusEl.textContent = t("alerts.webhookMaskedUrl");
    return;
  }
  // `required` is only true once nothing is saved yet (renderWebhookUrl()),
  // so this also covers "Save pressed on a fresh, empty form" with the
  // browser's own message, matching N16's ask for webhook URL errors.
  if (!urlEl.reportValidity()) return;
  const secret = $("fp-webhook-secret").value;
  try {
    await api("/api/alerts/channels/webhook", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url || undefined, secret: secret || undefined }),
    });
    $("fp-webhook-secret").value = "";
    await reload();
  } catch (err) {
    if (err.message !== "Locked") statusEl.textContent = mappedError(err, WEBHOOK_VALIDATION_KEYS);
  }
}

export async function removeWebhook(reload) {
  try {
    await api("/api/alerts/channels/webhook", { method: "DELETE" });
    await reload();
  } catch (err) {
    if (err.message !== "Locked") $("fp-webhook-status").textContent = err.message;
  }
}

/** lock.js purgeRenderedData() hook, via alerts_channels.js's purgeChannels():
 *  blank the field/status/secret -- none of it may survive a lock. */
export function purgeWebhook() {
  renderWebhookSection({ configured: false });
  $("fp-webhook-status").textContent = "";
  const secret = $("fp-webhook-secret");
  if (secret) secret.value = "";
}
