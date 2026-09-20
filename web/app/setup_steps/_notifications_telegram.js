/*
 * The Telegram controls of the wizard's Notifications step.
 *
 * Purpose    : Take a bot token and wait for the user to message the bot, the
 *              same `POST /api/alerts/channels/telegram/setup?wait=` long poll
 *              the Alerts tab uses (specs/onboarding.md § 4 row 6).
 * Inputs     : the channel section element, and the channel's own state from
 *              GET /api/alerts/channels.
 * Outputs    : the button, token field and status line, appended to the section.
 * Constraints: Its own file because the Alerts tab's copy of this flow reads
 *              elements that live inside #app-shell, which is hidden while the
 *              wizard is open, so it cannot be called from here. The route,
 *              body and wait budget are identical to that copy's.
 */
"use strict";

import { t } from "../i18n.js";

/** Seconds the server holds the request open, matching alerts.js. */
const WAIT_SECONDS = 120;

export function telegramControls(section, value) {
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
      const res = await fetch(`/api/alerts/channels/telegram/setup?wait=${WAIT_SECONDS}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bot_token: token.value.trim() }),
        signal: AbortSignal.timeout((WAIT_SECONDS + 5) * 1000),
      });
      const body = await res.json().catch(() => ({}));
      status.textContent =
        res.status === 200
          ? t("setup.notifications.connected", { chat: body.chat_title })
          : body.detail || `${res.status} ${res.statusText}`;
      token.value = "";
    } catch (err) {
      status.textContent = err.message;
    }
  });

  section.append(token, connect, status);
}
