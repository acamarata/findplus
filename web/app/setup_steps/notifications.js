/*
 * Onboarding step 6 — Notifications (optional).
 *
 * Purpose    : Offer one section per alert channel, each led by that channel's
 *              own disclosure, so nobody turns a channel on before reading
 *              what it does (specs/onboarding.md § 4 row 6, loop-2 F3).
 * Inputs     : ctx.api / ctx.postJson / ctx.state, handed down by the Wizard.
 * Outputs    : DOM inside the step container; the Telegram long-poll setup
 *              route; the Tauri `request_notification_permission` command.
 * Constraints: A channel with no honesty sentence of its own is not offered at
 *              all. The honesty paragraphs are appended BEFORE the channel's
 *              controls, never after. The native section exists only when
 *              window.__findplus_native is true (R-P2-13) and its button is
 *              the sole trigger of the OS permission prompt (R-P2-9). WhatsApp
 *              gets the same inline phone/API-key/Save/Test controls Telegram
 *              does (R-P2-28 point 3); only Webhook still falls to the
 *              "configure later" link, which now carries the app's link
 *              styling instead of the browser default (F5).
 */
"use strict";

import { t } from "../i18n.js";
import { telegramControls } from "./_notifications_telegram.js";
import { whatsappControls } from "./_notifications_whatsapp.js";

/** Channel id -> the /api/config.notices ids that must be shown with it. */
const CHANNEL_NOTICE_KEYS = {
  telegram: ["alerts_latency"],
  webhook: ["alerts_latency"],
  // whatsapp_setup (the CallMeBot connect steps) joins whatsapp_relay (the
  // third-party-relay disclosure) above the fields, matching the settings
  // card's own #fp-wa-relay-notice + #fp-wa-instructions pair (T0 addendum
  // B3, e13/blind-gp-adjudicated.md).
  whatsapp: ["whatsapp_relay", "whatsapp_setup"],
  native: ["native_generic", "alerts_locked"],
};

/** The live step's container, captured on render. */
let host = null;

function footnote(text) {
  const p = document.createElement("p");
  p.className = "fp-wizard-footnote";
  p.textContent = text || "";
  return p;
}

function nativeControls(section) {
  const status = document.createElement("span");
  status.className = "fp-setup-permission-status";
  const enable = document.createElement("button");
  enable.type = "button";
  enable.className = "btn";
  enable.id = "fp-setup-enable-notifications";
  enable.textContent = t("setup.notifications.enable");
  enable.addEventListener("click", async () => {
    try {
      const result = await window.__TAURI__.core.invoke("request_notification_permission");
      status.textContent = t(`setup.notifications.permission_${String(result).toLowerCase()}`);
    } catch (err) {
      status.textContent = err.message || String(err);
    }
  });
  section.append(enable, status);
}

function laterLink(section) {
  const link = document.createElement("a");
  // UAT U17: webhook setup lives in the Alerts tab, not Settings -- "#settings"
  // was a dead end. main.js's applyHashRoute() switches to the Alerts tab and
  // scrolls #fp-webhook-section into view for this hash.
  link.href = "#alerts-webhook";
  link.textContent = t("setup.notifications.configure_later");
  section.append(link);
}

export function renderChannelSection(key, value, noticeKeys, ctx) {
  const section = document.createElement("section");
  section.dataset.channel = key;
  const heading = document.createElement("h3");
  heading.textContent = t(`setup.notifications.${key}`);
  section.append(heading);

  const notices = (ctx.state.config && ctx.state.config.notices) || {};
  // Disclosure first, controls after: the order is the point of this section.
  noticeKeys.forEach((id) => section.append(footnote(notices[id])));

  if (key === "native") nativeControls(section);
  else if (key === "telegram") telegramControls(section, value, ctx);
  else if (key === "whatsapp") whatsappControls(section, value, ctx);
  else laterLink(section);
  return section;
}

/**
 * Every channel the server reports, plus native on a desktop build.
 *
 * `GET /api/alerts/channels` describes the channels that store credentials;
 * native stores none, so it never appears there. Without this line it could
 * never be offered, and R-P2-9 makes this step's button the only place Find+
 * is allowed to ask for the OS notification permission.
 */
function channelKeys(channels) {
  const keys = Object.keys(channels);
  if (window.__findplus_native === true && !keys.includes("native")) keys.push("native");
  return keys;
}

export default {
  id: "notifications",
  canSkip: true,
  render(container) {
    container.textContent = "";
    const heading = document.createElement("h2");
    heading.textContent = t("setup.notifications.title");
    container.append(heading);
    host = container;
  },
  async onEnter(ctx) {
    const channels = await ctx.api("/api/alerts/channels");
    for (const key of channelKeys(channels)) {
      const noticeKeys = CHANNEL_NOTICE_KEYS[key];
      if (!noticeKeys) continue;
      if (key === "native" && window.__findplus_native !== true) continue;
      host.append(renderChannelSection(key, channels[key], noticeKeys, ctx));
    }
  },
};
