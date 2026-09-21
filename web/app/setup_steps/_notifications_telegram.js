/*
 * The Telegram controls of the wizard's Notifications step.
 *
 * Purpose    : Take a bot token and wait for the user to message the bot, the
 *              same `POST /api/alerts/channels/telegram/setup?wait=` long poll
 *              the Alerts tab uses (specs/onboarding.md § 4 row 6).
 * Inputs     : ctx (for api()), the channel section element, and the channel's
 *              own state from GET /api/alerts/channels.
 * Outputs    : the button, token field and status line, appended to the section.
 * Constraints: Its own file because the Alerts tab's copy of this flow reads
 *              elements that live inside #app-shell, which is hidden while the
 *              wizard is open, so it cannot be called from here. The route,
 *              body and wait budget are identical to that copy's. The two
 *              help lines (T0 addendum B6, e13/blind-gp-adjudicated.md)
 *              mirror `findplus alerts telegram-setup`'s own instructions
 *              (cli/alerts.py): where the token comes from, and how Find+
 *              finds the chat id.
 */
"use strict";

import { t } from "../i18n.js";

/** Seconds the server holds the request open, matching alerts.js. */
const WAIT_SECONDS = 120;

/** Where the token comes from, and how Find+ finds the chat id — same content
 * `findplus alerts telegram-setup` prints, never invented copy. */
function helpLines() {
  const frag = document.createDocumentFragment();
  const tokenHelp = document.createElement("p");
  tokenHelp.className = "modal-note";
  tokenHelp.textContent = t("setup.notifications.telegram_help_token");
  const chatHelp = document.createElement("p");
  chatHelp.className = "modal-note";
  chatHelp.textContent = t("setup.notifications.telegram_help_chat");
  frag.append(tokenHelp, chatHelp);
  return frag;
}

export function telegramControls(section, value, ctx) {
  section.append(helpLines());

  const token = document.createElement("input");
  token.type = "password";
  token.id = "fp-setup-tg-token";
  token.placeholder = t("setup.notifications.token_placeholder");

  const status = document.createElement("p");
  status.className = "modal-note";
  if (value && value.configured) status.textContent = t("setup.notifications.already_connected");

  const connect = document.createElement("button");
  connect.type = "button";
  connect.className = "btn";
  connect.textContent = t("setup.notifications.connect");
  connect.addEventListener("click", async () => {
    if (!token.value.trim()) {
      status.textContent = t("setup.notifications.enter_token");
      return;
    }
    status.textContent = t("setup.notifications.waiting");
    try {
      // Through api(), not a raw fetch: a lock that lands mid-poll answers 401,
      // and only api() turns that into the lock screen rather than the words
      // "401 Unauthorized" in a status line (CR-C-E11 F5).
      const body = await ctx.api(`/api/alerts/channels/telegram/setup?wait=${WAIT_SECONDS}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bot_token: token.value.trim() }),
        signal: AbortSignal.timeout((WAIT_SECONDS + 5) * 1000),
      });
      status.textContent = t("setup.notifications.connected", { chat: body.chat_title });
    } catch (err) {
      status.textContent = err.message;
    } finally {
      // In a finally: an abort or a rejected token must not leave the secret
      // sitting in the field for the rest of the session.
      token.value = "";
    }
  });

  section.append(token, connect, status);
}
