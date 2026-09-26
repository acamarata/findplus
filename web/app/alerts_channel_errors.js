/*
 * Alerts tab: shared "raw server detail -> catalog sentence" mapping.
 *
 * Purpose    : routes_alerts_channels.py/routes_alerts_telegram.py's 422
 *              `detail` strings are raw, un-localized English (UAT U19,
 *              widened by UAT6 N16 to webhook/whatsapp) -- never fit to show
 *              a user directly. Each channel keeps its own small table of
 *              the details it actually recognises; this is only the lookup
 *              they all share, split out so alerts_channels.js and
 *              alerts_webhook.js (both PRI rule-7 300-line file cap
 *              splits) can use it without importing one another.
 * Inputs     : None -- a pure function.
 * Outputs    : mappedError(err, table).
 * Constraints: An unrecognised detail falls through to `err.message`
 *              unchanged rather than hiding it -- better a plain English
 *              sentence nobody localized than a blank status line.
 */
"use strict";
import { t } from "./i18n.js";

/** `err` from a failed api() call; `table` maps a known raw `detail` string
 *  to the catalog key that replaces it. */
export function mappedError(err, table) {
  return table[err.message] ? t(table[err.message]) : err.message;
}
