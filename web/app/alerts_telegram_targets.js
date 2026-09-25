/*
 * Alerts tab: the Telegram targets field, "Find chat IDs" helper, and the
 * per-target "Send test" result line. Split out of alerts_channels.js at the
 * PRI rule-7 300-line file cap (multi-target Telegram support pushed it
 * over).
 *
 * Purpose    : Let a person type/paste a comma-separated list of chat ids or
 *              @usernames directly (the owner's ask: notify a group, a
 *              person, or several people), or discover ids via "Find chat
 *              IDs" (GET /api/alerts/channels/telegram/updates -- reads the
 *              saved bot's pending getUpdates, never consumes them) and add
 *              them with one click.
 * Inputs     : GET/PUT /api/alerts/channels/telegram/targets, GET .../updates.
 * Outputs    : DOM under #fp-tg-targets/#fp-tg-chats-list; re-exports for
 *              alerts_channels.js (loadChannels/wireChannelControls/purge).
 * Constraints: Never renders over a field the user is mid-typing in (same
 *              renderWebhookUrl() pattern alerts_channels.js already uses).
 */
"use strict";
import { $ } from "./state.js";
import { t } from "./i18n.js";
import { api } from "./api.js";

/** The targets field only, never on top of what someone is mid-typing --
 *  same reasoning as alerts_channels.js's renderWebhookUrl(). */
export function renderTelegramTargets(telegram) {
  const el = $("fp-tg-targets");
  if (document.activeElement === el) return;
  el.value = telegram.configured ? telegram.targets || "" : "";
}

/** `results`: [{target, status, error}], from POST /api/alerts/test's
 *  per-target breakdown (owner ask: "Send test" reports per target). One
 *  line per target, joined with "; " -- the status line stays one element,
 *  matching every other channel's single-line status here. */
export function formatTelegramTestResults(results) {
  return (results || [])
    .map((r) =>
      r.status === "sent"
        ? t("alerts.testTargetSent", { target: r.target })
        : t("alerts.testTargetFailed", { target: r.target, error: r.error || t("common.unknownError") }),
    )
    .join("; ");
}

async function saveTelegramTargets() {
  const statusEl = $("fp-tg-targets-status");
  const targets = $("fp-tg-targets").value.trim();
  if (!targets) {
    statusEl.textContent = t("alerts.enterTargets");
    return;
  }
  try {
    const body = await api("/api/alerts/channels/telegram/targets", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets }),
    });
    statusEl.textContent = t("alerts.targetsSaved");
    renderTelegramTargets(body.telegram);
  } catch (err) {
    if (err.message !== "Locked") statusEl.textContent = err.message;
  }
}

/** Appends `chatId` to the targets field, comma-separated, deduped -- the
 *  "Find chat IDs" list's own "Add" action. Does not save by itself: the
 *  user still clicks "Save targets" (or edits further first). */
function addTargetToField(chatId) {
  const field = $("fp-tg-targets");
  const existing = field.value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
  if (!existing.includes(chatId)) existing.push(chatId);
  field.value = existing.join(", ");
}

function renderChatsList(chats) {
  const list = $("fp-tg-chats-list");
  while (list.firstChild) list.removeChild(list.firstChild);
  const statusEl = $("fp-tg-targets-status");
  if (!chats.length) {
    list.classList.add("hidden");
    statusEl.textContent = t("alerts.noUpdatesYet");
    return;
  }
  statusEl.textContent = "";
  for (const chat of chats) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${chat.title || chat.username || chat.id} (${chat.type}) — ${chat.id}`;
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "btn btn-secondary";
    addBtn.textContent = t("alerts.addTarget");
    addBtn.addEventListener("click", () => addTargetToField(chat.id));
    li.append(label, addBtn);
    list.appendChild(li);
  }
  list.classList.remove("hidden");
}

async function findTelegramChats() {
  const statusEl = $("fp-tg-targets-status");
  statusEl.textContent = t("alerts.findingChats");
  try {
    const body = await api("/api/alerts/channels/telegram/updates");
    renderChatsList(body.chats || []);
  } catch (err) {
    if (err.message !== "Locked") statusEl.textContent = err.message;
  }
}

export function wireTelegramTargetsControls() {
  $("fp-tg-save-targets").addEventListener("click", saveTelegramTargets);
  $("fp-tg-find-chats").addEventListener("click", findTelegramChats);
}

/** lock.js purgeRenderedData() hook, via alerts_channels.js's purgeChannels():
 *  blank the field and status, and collapse any found-chats list -- none of
 *  it may survive a lock. */
export function purgeTelegramTargets() {
  $("fp-tg-targets").value = "";
  $("fp-tg-targets-status").textContent = "";
  renderChatsList([]);
}
