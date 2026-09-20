/*
 * Alerts tab: Telegram setup, webhook config, widget toggle.
 *
 * Purpose    : Surface E6's alerts backend in the dashboard. The rules table
 *              and add-rule dialog live in alerts_rules.js (split out at the
 *              PRI rule-7 300-line file cap); this module owns wiring them
 *              in, plus the two channel sections and the widget toggle.
 * Inputs     : GET/POST/PUT/DELETE under /api/alerts/*; GET /api/settings/
 *              widget.show_map.
 * Outputs    : The two channel sections inside #tab-alerts (static markup
 *              in index.html); rules table/dialog via alerts_rules.js.
 * Constraints: textContent only, never raw markup — API strings can never
 *              run as script. Bot token lives only in the fetch body, masked
 *              field clears on focus. Widget toggle: per-key GET/PUT/POST
 *              /api/settings/widget.show_map (matches app.start_at_login;
 *              build-notes.md § E10-S2); GET returns `{"widget.show_map": bool}`.
 */
"use strict";
import { $ } from "./state.js";
import { t } from "./i18n.js";
import { api } from "./api.js";
import {
  fillOptions,
  loadRules,
  openAddRuleDialog,
  renderRulesTable,
  saveRule,
  updateRuleTargetVisibility,
} from "./alerts_rules.js";
import { loadDeliveries, purgeDeliveries } from "./alerts_deliveries.js";
const WIDGET_SETTING = "/api/settings/widget.show_map";
export function init() {
  wireStaticControls();
  injectLatencyFallback();
  refreshAll();
}
export async function refreshAll() {
  // A 401 here already showed the lock screen; loadWidgetToggle() runs either way.
  try { await loadChannels(); await loadRules(); await loadDeliveries(); } catch (_) { /* locked or unreachable */ }
  await loadWidgetToggle();
}
function injectLatencyFallback() {
  const el = $("fp-alerts-latency-notice");
  if (el && !el.textContent) {
    el.textContent = "Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late.";
  }
}
function wireStaticControls() {
  $("fp-tg-token").addEventListener("focus", () => clearMaskedToken($("fp-tg-token")));
  $("fp-wa-apikey").addEventListener("focus", () => clearMaskedToken($("fp-wa-apikey")));
  $("fp-wa-save").addEventListener("click", saveWhatsapp);
  $("fp-wa-test").addEventListener("click", sendWhatsappTest);
  $("fp-wa-clear").addEventListener("click", clearWhatsappChannel);
  $("fp-tg-connect").addEventListener("click", startTelegramSetup);
  $("fp-tg-test").addEventListener("click", sendTelegramTest);
  $("fp-tg-clear").addEventListener("click", clearTelegramChannel);
  $("fp-webhook-save").addEventListener("click", saveWebhook);
  $("fp-webhook-remove").addEventListener("click", removeWebhook);
  $("fp-add-rule-btn").addEventListener("click", openAddRuleDialog);
  $("fp-rule-save").addEventListener("click", saveRule);
  $("fp-rule-cancel").addEventListener("click", () => $("fp-add-rule-dialog").close());
  $("fp-rule-target-device").addEventListener("change", updateRuleTargetVisibility);
  $("fp-rule-target-group").addEventListener("change", updateRuleTargetVisibility);
  wireWidgetToggle();
}
/* channels */
export async function loadChannels() {
  const channels = await api("/api/alerts/channels");
  renderTelegramSection(channels.telegram);
  renderWebhookSection(channels.webhook);
  renderWhatsappSection(channels.whatsapp);
}
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
  $("fp-tg-status").textContent = "";
}
function renderWebhookSection(webhook) {
  $("fp-webhook-url").value = webhook.configured ? webhook.url || "" : "";
  setVisibleText(
    $("fp-webhook-current"),
    webhook.configured &&
      t("alerts.webhookCurrent", { url: webhook.url }) +
        (webhook.has_secret ? t("alerts.webhookSecretSet") : ""),
  );
}
/**
 * WhatsApp (CallMeBot) section.
 *
 * The phone field shows `phone_masked` and is edited in the clear: the backend
 * never returns the raw number, so there is nothing left to protect by
 * clearing it on focus. The apikey has no masked form in the API contract
 * (notifications.md §1 returns only `{configured, phone_masked}`), so it gets a
 * fixed placeholder rather than the token's reveal-last-4 shape.
 */
function renderWhatsappSection(whatsapp) {
  const phone = $("fp-wa-phone");
  const apikey = $("fp-wa-apikey");
  if (whatsapp && whatsapp.configured) {
    phone.value = whatsapp.phone_masked || "";
    apikey.value = "••••••••";
    apikey.classList.add("fp-token-masked");
  } else {
    phone.value = "";
    apikey.value = "";
    apikey.classList.remove("fp-token-masked");
  }
  setVisibleText(
    $("fp-wa-connected"),
    whatsapp &&
      whatsapp.configured &&
      whatsapp.phone_masked &&
      t("alerts.whatsapp.connected", { phone: whatsapp.phone_masked }),
  );
  $("fp-wa-status").textContent = "";
}
async function saveWhatsapp() {
  const phone = $("fp-wa-phone").value.trim();
  const apikey = $("fp-wa-apikey").value.trim();
  if (!phone || !apikey) return;
  try {
    await api("/api/alerts/channels/whatsapp", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, apikey }),
    });
    await loadChannels();
  } catch (err) {
    $("fp-wa-status").textContent = err.message;
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
  await api("/api/alerts/channels/whatsapp", { method: "DELETE" });
  await loadChannels();
}
/** Status code -> catalog key. Built at call time so t() reads the loaded catalog. */
const SETUP_ERROR_KEYS = {
  408: "alerts.setupErrorTimeout",
  409: "alerts.setupErrorConflict",
};
async function startTelegramSetup() {
  const statusEl = $("fp-tg-status");
  const token = $("fp-tg-token").value.trim();
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
      statusEl.textContent = t("alerts.connectionFailed", { detail: await errorDetail(res) });
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
    statusEl.textContent =
      result.status === "sent"
        ? t("alerts.testSent")
        : t("alerts.testFailed", { error: result.error || t("common.unknownError") });
  } catch (err) {
    statusEl.textContent = t("alerts.testFailed", { error: err.message });
  }
}
async function clearTelegramChannel() {
  await fetch("/api/alerts/channels/telegram", { method: "DELETE" });
  await loadChannels();
}
async function saveWebhook() {
  const url = $("fp-webhook-url").value.trim();
  const secret = $("fp-webhook-secret").value;
  if (!url) return;
  try {
    await api("/api/alerts/channels/webhook", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, secret: secret || null }),
    });
    $("fp-webhook-secret").value = "";
    await loadChannels();
  } catch (_) { /* api() already surfaced the lock screen or an error */ }
}
async function removeWebhook() {
  await fetch("/api/alerts/channels/webhook", { method: "DELETE" });
  await loadChannels();
}
/* widget toggle */
async function loadWidgetToggle() {
  const toggle = $("fp-widget-map-toggle");
  if (!toggle) return;
  try {
    toggle.checked = (await api(WIDGET_SETTING))["widget.show_map"] === true;
  } catch (_) { /* locked at boot; a later refreshAll() after unlock repopulates it */ }
}
function wireWidgetToggle() {
  const toggle = $("fp-widget-map-toggle");
  if (!toggle) return;
  toggle.addEventListener("change", async (e) => {
    try {
      await api(WIDGET_SETTING, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: e.target.checked }),
      });
    } catch (_) { /* best-effort; the checkbox already reflects the choice */ }
  });
}
/** lock.js purgeRenderedData() hook: device/place names must not survive the lock screen. */
export function purge() {
  renderRulesTable([]);
  purgeDeliveries();
  renderTelegramSection({ configured: false });
  renderWebhookSection({ configured: false });
  renderWhatsappSection({ configured: false });
  $("fp-tg-status").textContent = "";
  $("fp-wa-status").textContent = "";
  ["fp-rule-place", "fp-rule-device", "fp-rule-group"].forEach((id) => fillOptions($(id), [], () => []));
  // renderTelegramSection/renderWebhookSection above already blank the token
  // and URL inputs. These two nothing else touches: a typed webhook secret and
  // the add-rule dialog's name (a closed <dialog> keeps its input values, so
  // both stay readable from DevTools behind the lock screen).
  ["fp-rule-name", "fp-webhook-secret"].forEach((id) => {
    const el = $(id);
    if (el) el.value = "";
  });
  const err = $("fp-rule-error");
  if (err) err.textContent = "";
  const dlg = $("fp-add-rule-dialog");
  if (dlg && dlg.open) dlg.close();
}
init();
