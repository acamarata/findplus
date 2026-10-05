/*
 * The Person page's action row: Send today's summary, Notify me, Edit person,
 * Full map.
 *
 * Purpose    : The four things a person does from this page. Sending says what
 *              happened in words (sent to where, or why it failed); Notify me is one tap
 *              (person_notify.js); Edit opens the person editor, not a group's.
 * Inputs     : The person, the day on screen, and `setStatus(text, kind)` which
 *              writes the page's live status line.
 * Outputs    : Fills #person-actions; POST /api/people/{id}/day/send.
 * Constraints: createElement/textContent only. A send is one click, one result,
 *              no retry loop: it is a message to other people's phones, so it
 *              never fires twice by itself. The button is disabled while the
 *              request is out, so a double click cannot send twice.
 */
"use strict";

import { $, todayLocal } from "./state.js";
import { notifyMe } from "./person_notify.js";
import { plural, t } from "./i18n.js";
import { sendDay, sendResult } from "./person_api.js";

function button(label, cls, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = cls;
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

async function send(btn, person, date, setStatus) {
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = t("person.act.sending");
  setStatus("", "");
  try {
    const result = sendResult(await sendDay(person.id, date));
    if (result.ok) {
      const where = result.channels.map((c) => t(`alerts.channels.${c}`));
      const base = where.length ? t("person.act.sent", { channels: where.join(", ") }) : t("person.act.sentPlain");
      setStatus(result.partial ? `${base} ${plural("person.act.partial", result.partial, { n: result.partial })}` : base, "ok");
    } else setStatus(t("person.act.failed", { message: result.message }), "err");
  } catch (err) {
    if (err.message !== "Locked") setStatus(t("person.act.failed", { message: err.message }), "err");
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

async function editPerson(person) {
  const { openPersonEditor } = await import("./person_editor.js");
  const { reload } = await import("./person_page.js");
  await openPersonEditor(person.id, reload);
}

async function fullMap(person) {
  window.location.hash = "";
  const groups = await import("./groups.js");
  groups.selectGroupById(person.id);
  (await import("./main.js")).switchTab("latest");
}

/** Fill the action row for `person` on `date`. */
export function renderActions(person, date, setStatus) {
  const send_ = button(date === todayLocal() ? t("person.act.send") : t("person.act.sendDay"), "fp-btn fp-btn--secondary", () => send(send_, person, date, setStatus));
  send_.id = "person-send";
  $("person-actions").replaceChildren(
    send_,
    button(t("person.act.notifyMe"), "fp-btn fp-btn--secondary", () => notifyMe(person, setStatus)),
    button(t("person.act.edit"), "fp-btn fp-btn--secondary", () => editPerson(person)),
    button(t("person.act.fullMap"), "fp-btn fp-btn--secondary", () => fullMap(person)),
  );
}

export function clearActions() {
  $("person-actions").replaceChildren();
}
