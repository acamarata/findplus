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
import { api } from "./api.js";
import {
  fillOptions,
  loadRules,
  openAddRuleDialog,
  renderRulesTable,
  saveRule,
  updateRuleTargetVisibility,
} from "./alerts_rules.js";
const WIDGET_SETTING = "/api/settings/widget.show_map";
export function init() {
  wireStaticControls();
  injectLatencyFallback();
  refreshAll();
}
export async function refreshAll() {
  // A 401 here already showed the lock screen; loadWidgetToggle() runs either way.
  try { await loadChannels(); await loadRules(); } catch (_) { /* locked or unreachable */ }
  await loadWidgetToggle();
}
function injectLatencyFallback() {
  const el = $("fp-alerts-latency-notice");
  if (el && !el.textContent) {
    el.textContent = "Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late.";
  }
}
function wireStaticControls() {
  $("fp-tg-token").addEventListener("focus", clearMaskedToken);
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
}
function clearMaskedToken() {
  const tokenInput = $("fp-tg-token");
  if (tokenInput.classList.contains("fp-token-masked")) {
    tokenInput.value = "";
    tokenInput.classList.remove("fp-token-masked");
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
    telegram.chat_title && `Connected: ${telegram.chat_title} (${telegram.bot_username || ""})`,
  );
  $("fp-tg-status").textContent = "";
}
function renderWebhookSection(webhook) {
  $("fp-webhook-url").value = webhook.configured ? webhook.url || "" : "";
  setVisibleText(
    $("fp-webhook-current"),
    webhook.configured && `Current: ${webhook.url}${webhook.has_secret ? " (secret set)" : ""}`,
  );
}
const SETUP_ERROR_TEXT = {
  408: "No message received. Send any message to your bot and try again.",
  409: "A webhook is already set on this bot. Remove it in BotFather first.",
};
async function startTelegramSetup() {
  const statusEl = $("fp-tg-status");
  const token = $("fp-tg-token").value.trim();
  if (!token) {
    statusEl.textContent = "Enter a bot token first.";
    return;
  }
  statusEl.textContent = "Waiting for a message to your bot (120 s)…";
  try {
    const res = await fetch("/api/alerts/channels/telegram/setup?wait=120", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_token: token }),
      signal: AbortSignal.timeout(125000),
    });
    if (res.status === 200) {
      const body = await res.json();
      statusEl.textContent = `Connected: ${body.chat_title}`;
      await loadChannels();
    } else if (SETUP_ERROR_TEXT[res.status]) {
      statusEl.textContent = SETUP_ERROR_TEXT[res.status];
    } else {
      statusEl.textContent = "Connection failed: " + (await errorDetail(res));
    }
  } catch (err) {
    statusEl.textContent = "Connection failed: " + err.message;
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
      result.status === "sent" ? "Test message sent." : `Test failed: ${result.error || "unknown error"}`;
  } catch (err) {
    statusEl.textContent = "Test failed: " + err.message;
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
  renderTelegramSection({ configured: false });
  renderWebhookSection({ configured: false });
  $("fp-tg-status").textContent = "";
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
