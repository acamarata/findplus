/*
 * The lock screen's wrong-PIN and lockout sentences.
 *
 * Purpose    : "Wrong PIN. Try again." said nothing about the five-try limit, so
 *              the lockout arrived without warning (UAT #15). After a refusal this
 *              asks the always-reachable /api/lock/status how many tries are left
 *              (or how long the wait is) and says so in a catalog sentence.
 * Inputs     : The error thrown by the unlock call (`status` 401, 429, 422).
 * Outputs    : The sentence for #lock-error.
 * Constraints: Never prints the server's own detail text (UAT6-N07: it named a
 *              terminal command). If the status call fails, the plain sentences
 *              are used, so a refusal always gets an answer.
 */
"use strict";

import { api } from "./api.js";
import { t, plural } from "./i18n.js";

/** `/api/lock/status`'s attempts_remaining and retry_after_seconds, or {} if unreachable. */
async function throttle() {
  try {
    return await api("/api/lock/status", { skipLock: true });
  } catch (_) {
    return {};
  }
}

/** The sentence for a refused unlock: wrong PIN with tries left, a timed wait, or a format error. */
export async function unlockErrorText(e) {
  if (e.status === 401) {
    const { attempts_remaining: left, retry_after_seconds: wait } = await throttle();
    if (wait > 0) return t("common.lockWait", { seconds: wait });
    if (Number.isInteger(left)) return plural("common.wrongPinLeft", left, { n: left });
    return t("common.wrongPinHint");
  }
  if (e.status === 429) {
    const { retry_after_seconds: wait } = await throttle();
    return wait > 0 ? t("common.lockWait", { seconds: wait }) : t("common.lockTooManyTries");
  }
  if (e.status === 422) return t("common.lockPinFormat");
  return t("common.lockUnlockFailed");
}
