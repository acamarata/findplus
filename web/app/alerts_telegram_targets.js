/*
 * Alerts tab: the Telegram targets field, its current-targets chips, the
 * "Find chat IDs" helper, and the per-target "Send test" result line. Split
 * out of alerts_channels.js at the PRI rule-7 300-line file cap (multi-target
 * Telegram support pushed it over).
 *
 * Purpose    : Let a person type/paste a comma-separated list of chat ids or
 *              @usernames directly (the owner's ask: notify a group, a
 *              person, or several people), or discover ids via "Find chat
 *              IDs" (GET /api/alerts/channels/telegram/updates -- reads the
 *              saved bot's pending getUpdates, never consumes them) and add
 *              them with one click. UAT6 N15 added the readable side: every
 *              currently-saved target renders as a removable chip labelled
 *              with its display name (channels_response()'s target_labels/
 *              target_ids, _alerts_channels_response.py), so a saved raw id
 *              like "-100222" is never the only thing on screen -- and gated
 *              the whole targets surface behind "a bot is connected" (there
 *              is nothing to send a target to otherwise).
 * Inputs     : GET/PUT /api/alerts/channels/telegram/targets, GET .../updates.
 * Outputs    : DOM under #fp-tg-targets/#fp-tg-current-targets/#fp-tg-chats-list;
 *              re-exports for alerts_channels.js (loadChannels/
 *              wireChannelControls/purge).
 * Constraints: Never renders over a field the user is mid-typing in (same
 *              renderWebhookUrl() pattern alerts_channels.js already uses).
 *              The comma-separated #fp-tg-targets input keeps its existing
 *              full-replace contract (it shows and edits the WHOLE target
 *              list, same as before N15) -- the chips are a read/remove-only
 *              view alongside it, never a second source of truth for Save.
 */
"use strict";
import { $ } from "./state.js";
import { t } from "./i18n.js";
import { api } from "./api.js";

/** The raw ids behind the current chip row, in the same order as their
 *  labels -- removeTarget() needs the id, chips only ever show the label. */
let currentTargetIds = [];

/** One removable chip per currently-saved target, or hidden with nothing
 *  saved. Reuses the existing pill (.fp-presence-chip, places.js) and
 *  button (.btn-secondary, this file's own "Add" buttons below) styles --
 *  no new CSS, this module owns none. */
function renderCurrentTargetsChips(telegram) {
  const list = $("fp-tg-current-targets");
  if (!list) return;
  while (list.firstChild) list.removeChild(list.firstChild);
  if (!telegram.configured || currentTargetIds.length === 0) {
    list.classList.add("hidden");
    return;
  }
  const labels = telegram.target_labels || [];
  currentTargetIds.forEach((id, index) => {
    const label = labels[index] || id;
    const li = document.createElement("li");
    const chip = document.createElement("span");
    chip.className = "fp-presence-chip";
    chip.textContent = label;
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn btn-secondary";
    removeBtn.textContent = t("common.remove");
    removeBtn.setAttribute("aria-label", t("alerts.removeTargetLabel", { target: label }));
    removeBtn.addEventListener("click", () => removeTarget(id));
    li.append(chip, removeBtn);
    list.appendChild(li);
  });
  list.classList.remove("hidden");
}

/** The targets field, its chips, and the Save/Find-chat-IDs buttons.
 *
 * UAT6 N15: Targets/Save targets/Find chat IDs used to be live before a bot
 * was ever connected, answering "Telegram not configured" only once clicked
 * -- disabled here instead, with the one-line reason
 * (#fp-tg-targets-disabled-reason, static markup) shown in its place.
 *
 * The field itself keeps its pre-N15 behaviour: never rendered over while
 * the user is mid-typing (same guard as alerts_channels.js's
 * renderWebhookUrl()), full stored CSV when connected, blank otherwise.
 */
export function renderTelegramTargets(telegram) {
  const el = $("fp-tg-targets");
  const configured = !!telegram.configured;
  $("fp-tg-save-targets").disabled = !configured;
  $("fp-tg-find-chats").disabled = !configured;
  el.disabled = !configured;
  $("fp-tg-targets-disabled-reason").classList.toggle("hidden", configured);
  currentTargetIds = configured ? telegram.target_ids || [] : [];
  renderCurrentTargetsChips(telegram);
  if (document.activeElement === el) return;
  el.value = configured ? telegram.targets || "" : "";
}

/** A chip's own Remove button: PUT the remaining ids (the same full-replace
 *  route Save targets uses). Removing the last target is refused client-side
 *  with the same "enter at least one" hint saveTelegramTargets() gives an
 *  empty field -- Clear (the whole-channel disconnect) is how the last
 *  target actually goes away, matching how Telegram/WhatsApp already work. */
async function removeTarget(id) {
  const statusEl = $("fp-tg-targets-status");
  const remaining = currentTargetIds.filter((existing) => existing !== id);
  if (remaining.length === 0) {
    statusEl.textContent = t("alerts.enterTargets");
    return;
  }
  try {
    const body = await api("/api/alerts/channels/telegram/targets", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets: remaining.join(",") }),
    });
    statusEl.textContent = t("alerts.targetsSaved");
    renderTelegramTargets(body.telegram);
  } catch (err) {
    if (err.message !== "Locked") statusEl.textContent = err.message;
  }
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
 *  blank the field and status, disable the surface (matching "nothing
 *  connected" -- purgeChannels() also blanks the token so there is nothing
 *  to reconnect to until unlock re-fetches the real state anyway), and
 *  collapse any found-chats list or target chips -- none of it may survive
 *  a lock. */
export function purgeTelegramTargets() {
  $("fp-tg-targets").value = "";
  $("fp-tg-targets").disabled = true;
  $("fp-tg-save-targets").disabled = true;
  $("fp-tg-find-chats").disabled = true;
  $("fp-tg-targets-disabled-reason").classList.remove("hidden");
  $("fp-tg-targets-status").textContent = "";
  currentTargetIds = [];
  renderChatsList([]);
  renderCurrentTargetsChips({ configured: false });
}
