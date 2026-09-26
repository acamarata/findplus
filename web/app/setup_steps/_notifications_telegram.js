/*
 * The Telegram controls of the wizard's Notifications step.
 *
 * Purpose    : Take a bot token and wait for the user to message the bot, the
 *              same `POST /api/alerts/channels/telegram/setup?wait=` long poll
 *              the Alerts tab uses (specs/onboarding.md § 4 row 6). Also
 *              offers the manual targets field + "Find chat IDs" helper (the
 *              owner's ask: notify a group, a person, or several people,
 *              comma-delimited) so a wizard user who already knows their
 *              chat id never has to message the bot at all.
 * Inputs     : ctx (for api()), the channel section element, and the channel's
 *              own state from GET /api/alerts/channels.
 * Outputs    : the button, token field and status line, appended to the section;
 *              PUT /api/alerts/channels/telegram/targets and
 *              GET /api/alerts/channels/telegram/updates.
 * Constraints: Its own file because the Alerts tab's copy of this flow reads
 *              elements that live inside #app-shell, which is hidden while the
 *              wizard is open, so it cannot be called from here. The route,
 *              body and wait budget are identical to that copy's. The two
 *              help lines (T0 addendum B6, e13/blind-gp-adjudicated.md)
 *              mirror `findplus alerts telegram-setup`'s own instructions
 *              (cli/alerts.py): where the token comes from, and how Find+
 *              finds the chat id.
 *              UAT6-N15: the targets field, Save and Find chat IDs were all
 *              live before a bot was even connected, and a click just
 *              answered "Telegram not configured" -- plain grey text
 *              indistinguishable from an ordinary status line. Every targets
 *              control now starts disabled until `value.configured`, enable()
 *              flips them the moment Connect succeeds (no re-render needed),
 *              and setNote() gives an actual error its own look (role="alert",
 *              the same `.fp-dialog-error` class the rest of the wizard uses)
 *              instead of the neutral `.modal-note` every message shared.
 */
"use strict";

import { t } from "../i18n.js";

/** Seconds the server holds the request open, matching alerts.js. */
const WAIT_SECONDS = 120;

/** UAT6-N15: one look for an info/success line, another for an error, on the
 * same element -- role="alert" only when it actually is one, so a screen
 * reader does not announce "Targets saved." as urgently as a failure. */
function setNote(el, text, kind = "info") {
  el.textContent = text || "";
  el.className = kind === "error" ? "fp-dialog-error" : "modal-note";
  if (kind === "error") el.setAttribute("role", "alert");
  else el.removeAttribute("role");
}

/** UAT7-N11: the token, targets, phone and API-key fields across the
 * Notifications step had a placeholder as their only name -- gone the moment
 * a value is typed, and never visible at all. Wraps `input` with a real,
 * always-visible `<label for>` instead, reusing the sign-in step's own
 * `.fp-signin-field`/`.fp-signin-label` pair rather than a second copy of the
 * same two rules in setup.css. */
function labeledField(id, labelText, input, extraClass = "") {
  const wrap = document.createElement("div");
  wrap.className = extraClass ? `fp-signin-field ${extraClass}` : "fp-signin-field";
  const label = document.createElement("label");
  label.className = "fp-signin-label";
  label.htmlFor = id;
  label.textContent = labelText;
  wrap.append(label, input);
  return wrap;
}

function addTargetToField(field, chatId) {
  const existing = field.value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
  if (!existing.includes(chatId)) existing.push(chatId);
  field.value = existing.join(", ");
}

function renderChatsList(list, statusEl, targetsField, chats) {
  while (list.firstChild) list.removeChild(list.firstChild);
  if (!chats.length) {
    list.classList.add("hidden");
    setNote(statusEl, t("alerts.noUpdatesYet"));
    return;
  }
  setNote(statusEl, "");
  for (const chat of chats) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${chat.title || chat.username || chat.id} (${chat.type}) · ${chat.id}`;
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "btn btn-secondary";
    addBtn.textContent = t("alerts.addTarget");
    addBtn.addEventListener("click", () => addTargetToField(targetsField, chat.id));
    li.append(label, addBtn);
    list.appendChild(li);
  }
  list.classList.remove("hidden");
}

function buildSaveTargetsButton(targets, targetsStatus, ctx) {
  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.id = "fp-setup-tg-save-targets";
  saveBtn.className = "btn btn-secondary";
  saveBtn.textContent = t("alerts.saveTargets");
  saveBtn.addEventListener("click", async () => {
    const raw = targets.value.trim();
    if (!raw) {
      setNote(targetsStatus, t("alerts.enterTargets"), "error");
      return;
    }
    try {
      await ctx.api("/api/alerts/channels/telegram/targets", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targets: raw }),
      });
      setNote(targetsStatus, t("alerts.targetsSaved"));
    } catch (err) {
      setNote(targetsStatus, err.message, "error");
    }
  });
  return saveBtn;
}

function buildFindChatsButton(targets, targetsStatus, chatsList, ctx) {
  const findBtn = document.createElement("button");
  findBtn.type = "button";
  findBtn.id = "fp-setup-tg-find-chats";
  findBtn.className = "btn btn-secondary";
  findBtn.textContent = t("alerts.findChatIds");
  findBtn.addEventListener("click", async () => {
    setNote(targetsStatus, t("alerts.findingChats"));
    try {
      const body = await ctx.api("/api/alerts/channels/telegram/updates");
      renderChatsList(chatsList, targetsStatus, targets, body.chats || []);
    } catch (err) {
      setNote(targetsStatus, err.message, "error");
    }
  });
  return findBtn;
}

/** The manual targets field, Save/Find-chat-IDs buttons and the found-chats
 * list -- split out of telegramControls() to keep that function under the
 * 50-line cap (PRI rule 7); the two buttons' own wiring is split again into
 * buildSaveTargetsButton()/buildFindChatsButton() for the same reason.
 * Returns `{ frag, enable() }`: UAT6-N15 needs to flip every control on the
 * instant a bot connects, without re-rendering the section from scratch. */
function targetsControls(value, ctx) {
  const connected = Boolean(value && value.configured);
  const frag = document.createDocumentFragment();
  const targets = document.createElement("input");
  targets.type = "text";
  targets.id = "fp-setup-tg-targets";
  // UAT7-N11: the shared alerts.telegramTargetsPlaceholder clipped to
  // "...separated by" at 375px; this step gets its own shorter placeholder
  // rather than shortening the Alerts tab's (wider, unclipped) copy too.
  targets.placeholder = t("setup.notifications.telegram_targets_placeholder");
  targets.disabled = !connected;
  if (connected) targets.value = value.targets || "";

  const help = document.createElement("p");
  help.className = "modal-note";
  help.textContent = connected
    ? t("alerts.telegramTargetsHelp")
    : t("setup.notifications.telegram_connect_first");

  const targetsStatus = document.createElement("p");
  targetsStatus.id = "fp-setup-tg-targets-status";
  targetsStatus.className = "modal-note";

  const chatsList = document.createElement("ul");
  chatsList.id = "fp-setup-tg-chats-list";
  chatsList.className = "hidden";

  const saveBtn = buildSaveTargetsButton(targets, targetsStatus, ctx);
  const findBtn = buildFindChatsButton(targets, targetsStatus, chatsList, ctx);
  saveBtn.disabled = !connected;
  findBtn.disabled = !connected;

  const actions = document.createElement("div");
  actions.className = "fp-alerts-actions";
  actions.append(saveBtn, findBtn);
  const targetsField = labeledField(targets.id, t("alerts.telegramTargets"), targets);
  frag.append(targetsField, help, actions, targetsStatus, chatsList);

  function enable() {
    targets.disabled = false;
    saveBtn.disabled = false;
    findBtn.disabled = false;
    help.textContent = t("alerts.telegramTargetsHelp");
  }
  return { frag, enable };
}

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

/** The actual long-poll POST, split out of the Connect handler below so that
 * one reads as status/enable() bookkeeping, not the network call itself.
 * Through ctx.api(), not a raw fetch: a lock that lands mid-poll answers 401,
 * and only api() turns that into the lock screen rather than the words "401
 * Unauthorized" in a status line (CR-C-E11 F5). */
function connectRequest(ctx, token) {
  return ctx.api(`/api/alerts/channels/telegram/setup?wait=${WAIT_SECONDS}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bot_token: token.value.trim() }),
    signal: AbortSignal.timeout((WAIT_SECONDS + 5) * 1000),
  });
}

/** The token field, Connect button and its status line -- split out of
 * telegramControls() to keep that function under the 50-line cap. */
function buildConnectRow(section, value, ctx, targetsHandle) {
  const token = document.createElement("input");
  token.type = "password";
  token.id = "fp-setup-tg-token";
  token.placeholder = t("setup.notifications.token_placeholder");
  // UAT7-N11: a short, distinct visible label beats repeating the long
  // instructional placeholder text once it disappears on input (UAT3 N26).
  // "fp-signin-field--inline" (setup.css): this row keeps Connect beside the
  // input, unlike the sign-in step's own full-row fields that
  // .fp-signin-field was built for.
  const tokenField = labeledField(token.id, t("field.telegramToken"), token, "fp-signin-field--inline");

  const status = document.createElement("p");
  status.className = "modal-note";
  if (value && value.configured) status.textContent = t("setup.notifications.already_connected");

  const connect = document.createElement("button");
  connect.type = "button";
  connect.id = "fp-setup-tg-connect";
  connect.className = "btn";
  connect.textContent = t("setup.notifications.connect");
  connect.addEventListener("click", async () => {
    if (!token.value.trim()) {
      setNote(status, t("setup.notifications.enter_token"), "error");
      return;
    }
    setNote(status, t("setup.notifications.waiting"));
    try {
      const result = await connectRequest(ctx, token);
      setNote(status, t("setup.notifications.connected", { chat: result.chat_title }));
      // UAT6-N15: a bot connected THIS session must free the targets
      // controls immediately, not only after the next full render.
      targetsHandle.enable();
    } catch (err) {
      setNote(status, err.message, "error");
    } finally {
      // In a finally: an abort or a rejected token must not leave the secret
      // sitting in the field for the rest of the session.
      token.value = "";
    }
  });
  section.append(tokenField, connect, status);
}

export function telegramControls(section, value, ctx) {
  section.append(helpLines());
  const targetsHandle = targetsControls(value, ctx);
  buildConnectRow(section, value, ctx, targetsHandle);
  section.append(targetsHandle.frag);
}
