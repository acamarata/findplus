/*
 * Alerts tab: Telegram setup, webhook config, rules table, widget toggle.
 *
 * Purpose    : Surface E6's alerts backend in the dashboard.
 * Inputs     : GET/POST/PUT/DELETE under /api/alerts/*; GET /api/places,
 *              state.devices, GET /api/groups (rule dialog).
 * Outputs    : The two channel sections, rules table and add-rule dialog
 *              inside #tab-alerts (static markup in index.html).
 * Constraints: textContent only, never raw markup — API strings
 *              (chat_title, bot_username) can never run as script. The
 *              bot token lives only in the fetch body; the masked field
 *              clears on focus. Widget toggle uses the per-key
 *              /api/settings/widget.show_map shape (matches the existing
 *              app.start_at_login route) instead of the ticket's literal
 *              generic PUT /api/settings {key,value}, which the real PUT
 *              does not accept — see build-notes.md § E10-S2.
 */
"use strict";
import { $, state } from "./state.js";
import { api } from "./api.js";
const WIDGET_SETTING = "/api/settings/widget.show_map";
export function init() {
  wireStaticControls();
  injectLatencyFallback();
  loadWidgetToggle();
  refreshAll();
}
export async function refreshAll() {
  try {
    await loadChannels();
    await loadRules();
  } catch (_) {
    // Locked or unreachable at boot; the lock screen / next refresh handles it.
  }
}
function injectLatencyFallback() {
  const el = $("fp-alerts-latency-notice");
  if (el && !el.textContent) {
    el.textContent =
      "Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late.";
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
  } catch (_) { /* no JSON body */ }
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
/* rules */
export async function loadRules() {
  renderRulesTable(await api("/api/alerts/rules"));
}
function ruleTargetLabel(rule) {
  if (rule.group_id) return rule.group_name || `group ${rule.group_id}`;
  return rule.device_name || rule.device_id || "—";
}
function cell(text) {
  const td = document.createElement("td");
  td.textContent = text;
  return td;
}
function buildRuleRow(rule) {
  const tr = document.createElement("tr");
  tr.append(
    cell(rule.name), cell(rule.place_name || "—"), cell(ruleTargetLabel(rule)),
    cell(rule.on_enter ? "yes" : "no"), cell(rule.on_exit ? "yes" : "no"), cell(rule.channel),
  );
  const actions = document.createElement("td");
  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.textContent = "Delete";
  delBtn.addEventListener("click", () => deleteRule(rule.id, rule.name));
  actions.appendChild(delBtn);
  tr.appendChild(actions);
  return tr;
}
function renderRulesTable(rules) {
  const tbody = $("fp-rules-tbody");
  if (!tbody) return;
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
  rules.forEach((rule) => tbody.appendChild(buildRuleRow(rule)));
}
async function deleteRule(id, name) {
  if (!window.confirm(`Delete rule "${name}"?`)) return;
  await fetch(`/api/alerts/rules/${id}`, { method: "DELETE" });
  await loadRules();
}
/* add-rule dialog */
function fillOptions(select, items, mapFn) {
  while (select.firstChild) select.removeChild(select.firstChild);
  items.forEach((item) => {
    const [value, label] = mapFn(item);
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    select.appendChild(opt);
  });
}
async function populateRuleSelects() {
  fillOptions($("fp-rule-place"), await api("/api/places"), (p) => [String(p.id), p.name]);
  fillOptions($("fp-rule-device"), state.devices, (d) => [d.device_id, d.name]);
  let groups = [];
  try {
    groups = await api("/api/groups");
  } catch (_) { /* unreachable too; an empty group select is harmless */ }
  fillOptions($("fp-rule-group"), groups, (g) => [String(g.id), g.name]);
}
function updateRuleTargetVisibility() {
  const isDevice = $("fp-rule-target-device").checked;
  $("fp-rule-device").classList.toggle("hidden", !isDevice);
  $("fp-rule-group").classList.toggle("hidden", isDevice);
}
async function openAddRuleDialog() {
  await populateRuleSelects();
  $("fp-rule-name").value = "";
  $("fp-rule-on-enter").checked = true;
  $("fp-rule-on-exit").checked = false;
  $("fp-rule-cooldown").value = "60";
  $("fp-rule-target-device").checked = true;
  updateRuleTargetVisibility();
  $("fp-add-rule-dialog").showModal();
}
async function saveRule() {
  const dlg = $("fp-add-rule-dialog");
  const isDevice = $("fp-rule-target-device").checked;
  const body = {
    name: $("fp-rule-name").value,
    place_id: Number($("fp-rule-place").value),
    device_id: isDevice ? $("fp-rule-device").value : null,
    group_id: isDevice ? null : Number($("fp-rule-group").value),
    on_enter: $("fp-rule-on-enter").checked,
    on_exit: $("fp-rule-on-exit").checked,
    channel: $("fp-rule-channel").value,
    cooldown_minutes: Number($("fp-rule-cooldown").value),
  };
  try {
    await api("/api/alerts/rules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    dlg.close();
    await loadRules();
  } catch (_) { /* dialog stays open with the user's input so nothing is lost */ }
}
/* widget toggle */
async function loadWidgetToggle() {
  const toggle = $("fp-widget-map-toggle");
  if (!toggle) return;
  try {
    toggle.checked = (await api(WIDGET_SETTING)).value === true;
  } catch (_) { /* route not registered yet (defect #36) or locked */ }
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
init();
