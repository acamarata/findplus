/*
 * "Updating past days...": a line that shows while Find+ rebuilds earlier days.
 *
 * Purpose    : After people are accepted or a place is saved, Find+ re-reads the
 *              history so past days gain their arrive and leave lines. That takes
 *              a while on a long history, so a small line says it is happening
 *              instead of the Person page looking out of date.
 * Inputs     : GET /api/people/replay -> {state: idle|running|done, done, total}.
 * Outputs    : A fixed status line (#fp-replay-line), removed when the work ends.
 * Constraints: The route may not exist on an older daemon: one 404 turns the
 *              whole feature off for the session, quietly. Polling stops on lock,
 *              and never runs more than one loop. createElement/textContent only.
 */
"use strict";

import { api } from "./api.js";
import { state } from "./state.js";
import { t } from "./i18n.js";

const POLL_MS = 1500;
const IDLE_TRIES = 3;
const MAX_POLLS = 400;

let off = false;
let running = false;

function line() {
  let el = document.getElementById("fp-replay-line");
  if (!el) {
    el = document.createElement("p");
    el.id = "fp-replay-line";
    el.className = "fp-replay";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
  }
  return el;
}

const clear = () => document.getElementById("fp-replay-line")?.remove();
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function show(info) {
  const total = Number(info.total) || 0;
  const done = Number(info.done) || 0;
  line().textContent = total ? t("people.replay.progress", { done, total }) : t("people.replay.running");
}

async function poll() {
  let idle = 0;
  for (let i = 0; i < MAX_POLLS && !state.locked; i += 1) {
    let info;
    try {
      info = await api("/api/people/replay");
    } catch (err) {
      if (err.status === 404) off = true;
      return;
    }
    if (info.state === "running") { idle = 0; show(info); }
    else if (info.state === "done" || ++idle >= IDLE_TRIES) {
      if (info.state === "done" && document.getElementById("fp-replay-line")) {
        line().textContent = t("people.replay.done");
        await pause(2500);
      }
      return;
    }
    await pause(POLL_MS);
  }
}

/** Start watching (call after people are accepted or a place is saved). Safe to call often. */
export async function watchReplay() {
  if (off || running || state.locked) return;
  running = true;
  try {
    await poll();
  } finally {
    running = false;
    clear();
  }
}

/** Lock purge: nothing to keep. */
export function purgeReplay() {
  clear();
}
