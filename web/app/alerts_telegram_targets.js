/*
 * Alerts tab: the Telegram targets chip row, the "Add chats" field, the
 * "Find chat IDs" helper, and the per-target "Send test" result line. Split
 * out of alerts_channels.js at the PRI rule-7 300-line file cap (multi-target
 * Telegram support pushed it over).
 *
 * Purpose    : Show every currently-saved target as a real chip (UAT7 N04:
 *              the old markup was a bulleted <ul> of small pills each
 *              followed by a separate full-width "Remove" button, with the
 *              same ids repeated below in a raw comma field a person had to
 *              retype to add one more) and let a person add new chats
 *              through a small "Add chats" field instead of re-showing the
 *              whole saved list. Adding still accepts a comma-separated
 *              list of chat ids or @usernames, or a "Find chat IDs"
 *              (GET /api/alerts/channels/telegram/updates -- reads the
 *              saved bot's pending getUpdates, never consumes them) pick.
 *              Removing a chip warns first when any alert rule actually
 *              uses that target (GET /api/alerts/rules -- a rule with
 *              telegram_targets: null uses every saved target, a rule with
 *              a subset uses it only if its id is in that subset); removing
 *              an unused target needs no confirmation, since nothing else
 *              changes as a result.
 * Inputs     : GET/PUT /api/alerts/channels/telegram/targets, GET .../updates,
 *              GET /api/alerts/rules (for the removal warning's rule count).
 * Outputs    : DOM under #fp-tg-targets/#fp-tg-current-targets/#fp-tg-chats-list;
 *              re-exports for alerts_channels.js (loadChannels/
 *              wireChannelControls/purge).
 * Constraints: Never renders over a field the user is mid-typing in (same
 *              renderWebhookUrl() pattern alerts_channels.js already uses).
 *              The #fp-tg-targets field is add-only now: it always renders
 *              empty, even with existing targets saved, and Add chats PUTs
 *              the existing ids plus the newly typed ones -- resolve_targets()
 *              (telegram_targets.py) keeps every unchanged id's stored label
 *              rather than re-deriving it, so removing or adding one target
 *              never resets the labels of the rest, and only a brand-new
 *              @name ever reaches the Bot API.
 */
"use strict";
import { $ } from "./state.js";
import { t, plural } from "./i18n.js";
import { api } from "./api.js";
import { confirmDialog } from "./components/confirm-dialog.js";

/** The raw ids behind the current chip row, in the same order as their
 *  labels -- removeTarget() needs the id, chips only ever show the label. */
let currentTargetIds = [];

/** How many enabled alert rules would lose this chat if it were removed --
 *  a rule with `telegram_targets: null` uses every saved target ("All
 *  chats"), a rule with a list uses it only when the id is in that list.
 *  Failure (fetch error) reads as "none", the same "unknown, don't block"
 *  posture alerts_rule_channels.js's connectedChannels() already uses --
 *  the warning is a courtesy, never a hard gate. */
async function countRulesUsing(chatId) {
  try {
    const rules = await api("/api/alerts/rules");
    return rules.filter(
      (r) =>
        r.channels.includes("telegram") &&
        (r.telegram_targets == null || r.telegram_targets.includes(chatId)),
    ).length;
  } catch (_) {
    return 0;
  }
}

/** One removable chip per currently-saved target, or hidden with nothing
 *  saved. A real chip row now (UAT7 N04): inline-flex, no bullets, a small
 *  "×" remove button per chip instead of a separate full-width "Remove". */
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
    li.className = "fp-chip";
    const text = document.createElement("span");
    text.textContent = label;
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "fp-chip-remove";
    removeBtn.textContent = "×";
    removeBtn.setAttribute("aria-label", t("alerts.removeTargetLabel", { target: label }));
    removeBtn.addEventListener("click", () => removeTarget(id, label));
    li.append(text, removeBtn);
    list.appendChild(li);
  });
  list.classList.remove("hidden");
}

/** The Add-chats field, the chip row, and the Add/Find-chat-IDs buttons.
 *
 * UAT6 N15: Targets/Save targets/Find chat IDs used to be live before a bot
 * was ever connected, answering "Telegram not configured" only once clicked
 * -- disabled here instead, with the one-line reason
 * (#fp-tg-targets-disabled-reason, static markup) shown in its place.
 *
 * UAT7 N04: the field itself is add-only -- it always renders empty, never
 * the stored comma list, so adding one chat never means retyping every
 * other one. The one exception is the same mid-typing guard
 * alerts_channels.js's renderWebhookUrl() uses: a render landing while the
 * field has focus never clobbers what is being typed.
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
  el.value = "";
}

/** A chip's own "×": warns first when `id` is still used by an enabled rule
 *  (UAT7 N04 -- naming how many, and what happens), then PUTs the remaining
 *  ids (the same full-replace route Add chats uses). Removing the last
 *  target is refused client-side with the same "enter at least one" hint
 *  addTelegramTargets() gives an empty field -- Clear (the whole-channel
 *  disconnect) is how the last target actually goes away, matching how
 *  Telegram/WhatsApp already work. */
async function removeTarget(id, label) {
  const statusEl = $("fp-tg-targets-status");
  const remaining = currentTargetIds.filter((existing) => existing !== id);
  if (remaining.length === 0) {
    statusEl.textContent = t("alerts.enterTargets");
    return;
  }
  const usedByCount = await countRulesUsing(id);
  if (usedByCount > 0) {
    const confirmed = await confirmDialog({
      title: t("alerts.confirmRemoveTarget", { label }),
      body: plural("alerts.confirmRemoveTargetUsedByRules", usedByCount, { label, count: usedByCount }),
      confirmLabel: t("common.remove"),
      danger: true,
    });
    if (!confirmed) return;
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

/** Add-chats: merges the field's newly typed, comma-separated entries onto
 *  the currently-saved ids and PUTs the full merged list (UAT7 N04) -- the
 *  route is still full-replace, but the caller here never has to retype the
 *  ids already saved. Only a brand-new "@name" in the field ever reaches
 *  the Bot API (telegram_targets.py's resolve_targets() reuses every
 *  already-saved id's own stored label with no request). */
async function addTelegramTargets() {
  const statusEl = $("fp-tg-targets-status");
  const field = $("fp-tg-targets");
  const newEntries = field.value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
  if (newEntries.length === 0) {
    statusEl.textContent = t("alerts.enterTargets");
    return;
  }
  try {
    const body = await api("/api/alerts/channels/telegram/targets", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets: [...currentTargetIds, ...newEntries].join(",") }),
    });
    field.value = "";
    statusEl.textContent = t("alerts.targetsSaved");
    renderTelegramTargets(body.telegram);
  } catch (err) {
    if (err.message !== "Locked") statusEl.textContent = err.message;
  }
}

/** Appends `chatId` to the Add-chats field, comma-separated, deduped --
 *  the "Find chat IDs" list's own "Add" action. Does not save by itself:
 *  the user still clicks "Add chats" (or edits further first). */
function addTargetToField(chatId) {
  const field = $("fp-tg-targets");
  const existing = field.value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
  if (!existing.includes(chatId)) existing.push(chatId);
  field.value = existing.join(", ");
}

/** UAT7 N04: a chat already saved (its id is in `currentTargetIds`) shows
 *  "Added" instead of an actionable "Add" -- clicking it again offered no
 *  new target and read as broken. */
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
    label.textContent = `${chat.title || chat.username || chat.id} (${chat.type}) ${chat.id}`;
    const alreadyAdded = currentTargetIds.includes(String(chat.id));
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "btn btn-secondary";
    addBtn.textContent = alreadyAdded ? t("alerts.chatAlreadyAdded") : t("alerts.addTarget");
    addBtn.disabled = alreadyAdded;
    if (!alreadyAdded) addBtn.addEventListener("click", () => addTargetToField(chat.id));
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
  $("fp-tg-save-targets").addEventListener("click", addTelegramTargets);
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
