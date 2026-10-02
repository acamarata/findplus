/*
 * Settings: the people section (daily summary, left-behind alerts, backup).
 *
 * Purpose    : One place for what the people features send and keep: the evening
 *              summary (on or off, when, where, for whom, send now), whether a
 *              left-behind tracker raises an alert, and the database backup line.
 * Inputs     : state.settings["people.digest"] (GET /api/settings), PATCH
 *              /api/settings {"people.digest": {...}}, GET/PUT /api/people/settings,
 *              POST /api/people/{id}/day/send; backups in settings_backup.js.
 * Outputs    : The #fp-settings-people section. Every control saves as it changes,
 *              like the rest of the dialog, and says "Saved." or why not.
 * Constraints: createElement/textContent only. Turning the last person off turns the
 *              summary off rather than meaning "everyone". The summary and alert
 *              honesty sentences are shown verbatim. purge() empties the section.
 */
"use strict";

import { api } from "./api.js";
import { t } from "./i18n.js";
import { $, state, todayLocal } from "./state.js";
import { fetchPeople, sendDay, sendResult } from "./person_api.js";
import { markSaved } from "./settings_saved.js";
import { backupSection } from "./settings_backup.js";

const DEFAULTS = { enabled: false, time: "20:00", people: [], channel: "auto" };
const JSON_HEADERS = { "Content-Type": "application/json" };

let digest = { ...DEFAULTS };
let people = [];
let status = null;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

const say = (text, kind) => { if (status) { status.textContent = text; status.className = `person-status${kind ? ` person-status--${kind}` : ""}`; } };

async function patchDigest(change, undo) {
  try {
    const body = await api("/api/settings", { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ "people.digest": change }) });
    digest = { ...DEFAULTS, ...(body["people.digest"] || { ...digest, ...change }) };
    if (state.settings) state.settings["people.digest"] = digest;
    markSaved();
    say("", "");
  } catch (err) {
    if (err.message === "Locked") return;
    if (undo) undo();
    say(t("person.settings.digestFailed", { message: err.message }), "err");
  }
}

function checkbox(id, label, checked, onChange) {
  const row = el("label", "setting-row");
  const box = el("input");
  box.type = "checkbox"; box.id = id; box.checked = checked;
  box.addEventListener("change", () => onChange(box));
  row.append(el("span", "", label), box);
  return { row, box };
}

function labelled(label, control) {
  const row = el("label", "setting-row");
  row.append(el("span", "", label), control);
  return row;
}

function chosen() {
  return digest.people.length ? new Set(digest.people) : new Set(people.map((p) => p.id));
}

function personRow(person, boxes) {
  const row = el("div", "setting-row person-digest-row");
  const label = el("label", "person-digest-name");
  const box = el("input");
  box.type = "checkbox"; box.dataset.personId = String(person.id); box.checked = chosen().has(person.id);
  box.addEventListener("change", () => onPeopleChange(boxes));
  label.append(box, el("span", "", person.name));
  const send = el("button", "btn btn-tiny", t("person.settings.sendNow"));
  send.type = "button";
  send.setAttribute("aria-label", t("person.settings.sendNowFor", { name: person.name }));
  send.addEventListener("click", () => sendNow(send, person));
  row.append(label, send);
  boxes.push(box);
  return row;
}

function onPeopleChange(boxes) {
  const ids = boxes.filter((b) => b.checked).map((b) => Number(b.dataset.personId));
  const master = $("person-digest-on");
  if (!ids.length) {
    say(t("person.settings.digestNobody"), "err");
    if (master && master.checked) { master.checked = false; patchDigest({ enabled: false }); }
    return;
  }
  patchDigest({ people: ids.length === people.length ? [] : ids });
}

async function sendNow(button, person) {
  button.disabled = true;
  say("", "");
  try {
    const result = sendResult(await sendDay(person.id, todayLocal()));
    const where = result.channels.map((c) => t(`alerts.channels.${c}`)).join(", ");
    say(result.ok ? (where ? t("person.act.sent", { channels: where }) : t("person.act.sentPlain")) : t("person.act.failed", { message: result.message }), result.ok ? "ok" : "err");
  } catch (err) {
    if (err.message !== "Locked") say(t("person.act.failed", { message: err.message }), "err");
  } finally {
    button.disabled = false;
  }
}

function digestControls() {
  const box = el("div", "person-digest");
  const on = checkbox("person-digest-on", t("person.settings.digestOn"), digest.enabled, (b) => patchDigest({ enabled: b.checked }, () => { b.checked = !b.checked; }));
  const time = el("input");
  time.type = "time"; time.id = "person-digest-time"; time.value = digest.time;
  time.addEventListener("change", () => time.value && patchDigest({ time: time.value }));
  const channel = el("select");
  channel.id = "person-digest-channel";
  [["auto", t("person.settings.channelAuto")], ["telegram", t("person.settings.channelTelegram")]].forEach(([v, label]) => {
    const o = el("option", "", label); o.value = v; o.selected = v === digest.channel; channel.appendChild(o);
  });
  channel.addEventListener("change", () => patchDigest({ channel: channel.value }));
  const boxes = [];
  const list = people.length ? people.map((p) => personRow(p, boxes)) : [el("p", "modal-note", t("person.settings.noPeople"))];
  const whose = el("p", "modal-note", t("person.settings.digestPeople"));
  box.append(on.row, labelled(t("person.settings.digestTime"), time), labelled(t("person.settings.digestChannel"), channel), whose, ...list);
  return box;
}

async function leftBehindControls() {
  const box = el("div", "person-left");
  let on = true;
  try { on = Boolean((await api("/api/people/settings")).left_behind_alerts); } catch (_) { /* default on */ }
  const row = checkbox("person-left-on", t("person.settings.leftOn"), on, async (b) => {
    try {
      await api("/api/people/settings", { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify({ left_behind_alerts: b.checked }) });
      markSaved();
    } catch (err) {
      b.checked = !b.checked;
      if (err.message !== "Locked") say(t("person.settings.leftFailed", { message: err.message }), "err");
    }
  });
  box.append(row.row, el("p", "modal-note", t("person.settings.leftNote")));
  return box;
}

/** Fill the section (called each time the Settings dialog opens). */
export async function loadPeopleSettings() {
  const host = $("fp-settings-people");
  if (!host) return;
  digest = { ...DEFAULTS, ...((state.settings && state.settings["people.digest"]) || {}) };
  try { people = await fetchPeople(); } catch (_) { people = []; }
  status = el("p", "person-status");
  status.setAttribute("role", "status");
  host.replaceChildren(
    el("h3", "", t("person.settings.heading")),
    el("h4", "ps-sub", t("person.settings.digestTitle")),
    el("p", "modal-note", t("person.settings.digestNote")),
    digestControls(),
    el("h4", "ps-sub", t("person.settings.leftTitle")),
    await leftBehindControls(),
    await backupSection(say),
    status,
    el("p", "modal-note", t("honesty.alertsLatency")),
    el("p", "modal-note", t("honesty.presenceStale")),
  );
}

/** Lock purge: person names must not stay in the closed dialog. */
export function purgePeopleSettings() {
  const host = $("fp-settings-people");
  if (host) host.replaceChildren();
  people = [];
  status = null;
}
