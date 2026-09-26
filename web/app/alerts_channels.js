"use strict";
import { $ } from "./state.js";
import { t } from "./i18n.js";
import { api } from "./api.js";
import {
  formatTelegramTestResults,
  purgeTelegramTargets,
  renderTelegramTargets,
  wireTelegramTargetsControls,
} from "./alerts_telegram_targets.js";
import { purgeWebhook, removeWebhook, renderWebhookSection, saveWebhook } from "./alerts_webhook.js";
import { mappedError } from "./alerts_channel_errors.js";

/** Blanks a masked credential field the first time it is focused for editing. */
function clearMaskedToken(el) {
  if (el.classList.contains("fp-token-masked")) {
    el.value = "";
    el.classList.remove("fp-token-masked");
  }
}
/** Shows `text` in `el`, or hides `el` when `text` is falsy. */
function setVisibleText(el, text) {
  el.textContent = text || "";
  el.classList.toggle("hidden", !text);
}

/** Status code -> catalog key. Built at call time so t() reads the loaded catalog. */
const SETUP_ERROR_KEYS = {
  408: "alerts.setupErrorTimeout",
  409: "alerts.setupErrorConflict",
};

/** UAT U19: a 422's `detail` is routes_alerts_channels.py's raw English
 *  (never localized), so the one client-known reason gets a catalog string;
 *  anything else still falls through to alerts.connectionFailed below rather
 *  than showing nothing. */
const VALIDATION_DETAIL_KEYS = {
  "bot_token must look like a BotFather token": "alerts.badBotTokenError",
};

/** UAT6 N16: routes_alerts_channels.py's put_whatsapp() 422 details are raw
 *  English too -- same VALIDATION_DETAIL_KEYS pattern as Telegram above. */
const WHATSAPP_VALIDATION_KEYS = {
  "phone must be E.164, e.g. +34123123123": "alerts.whatsapp.invalidPhone",
  "apikey must be alphanumeric, at least 4 characters": "alerts.whatsapp.invalidApikey",
};

function renderTelegramSection(telegram) {
  const tokenInput = $("fp-tg-token");
  if (telegram.configured) {
    tokenInput.value = "••••••••" + (telegram.bot_token_masked || "").slice(-4);
    tokenInput.classList.add("fp-token-masked");
  } else {
    tokenInput.value = "";
    tokenInput.classList.remove("fp-token-masked");
  }
  setVisibleText(
    $("fp-tg-connected"),
    telegram.chat_title &&
      t("alerts.connectedAsWithBot", { chat: telegram.chat_title, bot: telegram.bot_username || "" }),
  );
  renderTelegramTargets(telegram);
  $("fp-tg-status").textContent = "";
}
/**
 * WhatsApp (CallMeBot) section.
 *
 * Neither input is prefilled with a masked value: `phone_masked` (`+34…23`)
 * is not a number the PUT would accept, and the apikey has no masked form in
 * the API contract at all (notifications.md §1 returns `{configured,
 * phone_masked}`). The masked number shows in the connected line instead.
 */
function renderWhatsappSection(whatsapp) {
  const apikey = $("fp-wa-apikey");
  const configured = !!(whatsapp && whatsapp.configured);
  // Bullets stand for "a key is stored", never for the key itself.
  $("fp-wa-phone").value = "";
  apikey.value = configured ? "••••••••" : "";
  apikey.classList.toggle("fp-token-masked", configured);
  const masked = configured && whatsapp.phone_masked;
  setVisibleText($("fp-wa-connected"), masked && t("alerts.whatsapp.connected", { phone: masked }));
  $("fp-wa-status").textContent = "";
}
async function saveWhatsapp() {
  const phoneEl = $("fp-wa-phone");
  const apikeyEl = $("fp-wa-apikey");
  const statusEl = $("fp-wa-status");
  // The bullets are a placeholder, not the key: saving them would replace a
  // working credential with punctuation while the card still said connected.
  clearMaskedToken(apikeyEl);
  const phone = phoneEl.value.trim();
  const apikey = apikeyEl.value.trim();
  // UAT6 N16: a silent focus() move read as a dead Save button -- a field
  // error names what is missing, matching every other channel's own Save.
  if (!phone || !apikey) {
    statusEl.textContent = t(phone ? "alerts.whatsapp.enterApikey" : "alerts.whatsapp.enterPhone");
    (phone ? apikeyEl : phoneEl).focus();
    return;
  }
  statusEl.textContent = "";
  try {
    await api("/api/alerts/channels/whatsapp", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, apikey }),
    });
    await loadChannels();
  } catch (err) {
    if (err.message !== "Locked") statusEl.textContent = mappedError(err, WHATSAPP_VALIDATION_KEYS);
  }
}
async function sendWhatsappTest() {
  const statusEl = $("fp-wa-status");
  try {
    const result = await api("/api/alerts/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel: "whatsapp" }),
    });
    statusEl.textContent =
      result.status === "sent"
        ? t("alerts.testSent")
        : t("alerts.testFailed", { error: result.error || t("common.unknownError") });
  } catch (err) {
    statusEl.textContent = t("alerts.testFailed", { error: err.message });
  }
}
async function clearWhatsappChannel() {
  try {
    await api("/api/alerts/channels/whatsapp", { method: "DELETE" });
    await loadChannels();
  } catch (err) {
    // Never an unhandled rejection; api() handles a 401 by itself.
    if (err.message !== "Locked") $("fp-wa-status").textContent = err.message;
  }
}
async function startTelegramSetup() {
  const statusEl = $("fp-tg-status");
  const tokenEl = $("fp-tg-token");
  // UAT6 N02: the same "never save the mask" bug the webhook URL had, checked
  // here instead of relying on the field having been focused first -- a
  // pointer-device paste, or a user who never clicks into an already-masked
  // field before pressing Connect, would otherwise send the bullet placeholder
  // as a bot token. `is_valid_bot_token` on the server rejects that shape
  // outright (it is never digits-colon-alnum), so nothing masked was ever
  // actually stored this way, but the round trip and its 422 were pointless.
  if (tokenEl.classList.contains("fp-token-masked")) {
    statusEl.textContent = t("alerts.enterBotToken");
    tokenEl.focus();
    return;
  }
  const token = tokenEl.value.trim();
  if (!token) {
    statusEl.textContent = t("alerts.enterBotToken");
    return;
  }
  statusEl.textContent = t("alerts.waitingForMessage");
  try {
    const res = await fetch("/api/alerts/channels/telegram/setup?wait=120", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_token: token }),
      signal: AbortSignal.timeout(125000),
    });
    if (res.status === 200) {
      const body = await res.json();
      statusEl.textContent = t("alerts.connectedAs", { chat: body.chat_title });
      await loadChannels();
    } else if (SETUP_ERROR_KEYS[res.status]) {
      statusEl.textContent = t(SETUP_ERROR_KEYS[res.status]);
    } else {
      const detail = await errorDetail(res);
      const mappedKey = res.status === 422 ? VALIDATION_DETAIL_KEYS[detail] : null;
      statusEl.textContent = mappedKey ? t(mappedKey) : t("alerts.connectionFailed", { detail });
    }
  } catch (err) {
    statusEl.textContent = t("alerts.connectionFailed", { detail: err.message });
  }
}
async function errorDetail(res) {
  try {
    const body = await res.json();
    if (body.detail) return body.detail;
  } catch (_) { /* no body */ }
  return `${res.status} ${res.statusText}`;
}
async function sendTelegramTest() {
  const statusEl = $("fp-tg-status");
  try {
    const result = await api("/api/alerts/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel: "telegram" }),
    });
    statusEl.textContent = result.results
      ? formatTelegramTestResults(result.results)
      : result.status === "sent"
        ? t("alerts.testSent")
        : t("alerts.testFailed", { error: result.error || t("common.unknownError") });
  } catch (err) {
    statusEl.textContent = t("alerts.testFailed", { error: err.message });
  }
}
async function clearTelegramChannel() {
  try {
    await api("/api/alerts/channels/telegram", { method: "DELETE" });
    await loadChannels();
  } catch (err) {
    // Never an unhandled rejection; api() handles a 401 by itself (loop2 B3).
    if (err.message !== "Locked") $("fp-tg-status").textContent = err.message;
  }
}

export async function loadChannels() {
  const channels = await api("/api/alerts/channels");
  renderTelegramSection(channels.telegram);
  renderWebhookSection(channels.webhook);
  renderWhatsappSection(channels.whatsapp);
}

export function wireChannelControls() {
  $("fp-tg-token").addEventListener("focus", () => clearMaskedToken($("fp-tg-token")));
  $("fp-wa-apikey").addEventListener("focus", () => clearMaskedToken($("fp-wa-apikey")));
  $("fp-wa-save").addEventListener("click", saveWhatsapp);
  $("fp-wa-test").addEventListener("click", sendWhatsappTest);
  $("fp-wa-clear").addEventListener("click", clearWhatsappChannel);
  $("fp-tg-connect").addEventListener("click", startTelegramSetup);
  $("fp-tg-test").addEventListener("click", sendTelegramTest);
  $("fp-tg-clear").addEventListener("click", clearTelegramChannel);
  wireTelegramTargetsControls();
  // saveWebhook()/removeWebhook() (alerts_webhook.js) take this module's own
  // loadChannels as their reload callback rather than importing it, so the
  // two files never import each other (see alerts_webhook.js's docstring).
  $("fp-webhook-save").addEventListener("click", () => saveWebhook(loadChannels));
  $("fp-webhook-remove").addEventListener("click", () => removeWebhook(loadChannels));
}

/** Masks #fp-tg-token before boot's GET /api/alerts/channels resolves, so the
 * field is never observably empty while that fetch is in flight -- a real
 * value (or a true "not configured" blank) replaces this placeholder the
 * moment renderTelegramSection() runs (E13 loop3 L3-3). */
export function showTelegramTokenPlaceholder() {
  const tokenInput = $("fp-tg-token");
  tokenInput.value = "••••••••";
  tokenInput.classList.add("fp-token-masked");
}

export function purgeChannels() {
  renderTelegramSection({ configured: false });
  purgeWebhook();
  renderWhatsappSection({ configured: false });
  $("fp-tg-status").textContent = "";
  $("fp-wa-status").textContent = "";
  purgeTelegramTargets();
}
