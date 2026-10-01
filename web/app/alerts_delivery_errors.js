/*
 * Alerts tab: turning a raw delivery error into one plain sentence.
 *
 * Purpose    : Split out of alerts_deliveries.js (PRI rule-7 300-line cap) so the
 *              delivery log, the webhook test and the rule dialog's test send
 *              all say "Couldn't reach Webhook (network)." instead of showing a
 *              Python exception.
 * Inputs     : The raw error text and the channel id.
 * Outputs    : friendlyErrorText(raw, channel).
 * Constraints: Pure and catalog-driven. The raw text is never lost: callers put
 *              it in a title attribute.
 */
"use strict";
import { t } from "./i18n.js";

/**
 * UAT6 N17: the Error column used to show whatever the channel's own client
 * library raised verbatim -- "HTTPSConnectionPool(host='api.telegram.org'…
 * NameResolutionError)" -- a Python exception repr, not something a user can
 * act on, and long enough to overflow the 375px pane on its own (no spaces
 * for the browser to wrap on). Each pattern below is a shape the channel
 * clients (requests/httpx under Telegram/webhook/WhatsApp) are actually
 * known to raise; anything unrecognised still gets a short, honest fallback
 * instead of the raw text. The raw text is never gone -- it sits in the
 * cell's `title` (cell()'s own convention) for anyone who needs it.
 */
const ERROR_PATTERNS = [
  [/NameResolution|getaddrinfo|Name or service not known|ConnectionError|HTTPSConnectionPool|HTTPConnectionPool|Connection refused|Network is unreachable/i, "alerts.deliveries.errorNetwork"],
  [/timed? ?out|TimeoutError|ReadTimeout|ConnectTimeout/i, "alerts.deliveries.errorTimeout"],
  [/\b401\b|\b403\b|Unauthorized|Forbidden|invalid token|bot was blocked/i, "alerts.deliveries.errorAuth"],
  // UAT7 N06: dispatch_send.py's own skip reason, verbatim ("telegram is not
  // configured") -- this used to fall through to the generic "Couldn't
  // deliver to {channel}." below, which reads like an attempted, failed send
  // rather than a channel dispatch never even tried.
  [/is not configured/i, "alerts.deliveries.errorNotConnected"],
];

/** The short catalog sentence for a raw error string, or the generic
 *  fallback when nothing above recognises its shape. */
export function friendlyErrorText(raw, channel) {
  const channelName = channel ? t("alerts.channels." + channel) : t("common.emptyValue");
  const match = ERROR_PATTERNS.find(([pattern]) => pattern.test(raw));
  return t(match ? match[1] : "alerts.deliveries.errorGeneric", { channel: channelName });
}

