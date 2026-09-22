/*
 * Apple accessory keys: register one from the dashboard instead of only
 * `findplus apple add-accessory` in a terminal (CF-P2-19).
 *
 * Purpose    : POST /api/apple/accessories with whichever body shape the key
 *              file implies, rendering the 413/422/409 errors
 *              routes_auth.py answers with inline, right beside the form.
 *              Split out of auth.js (which mounts and purges this module)
 *              to keep auth.js under the 300-line cap.
 * Inputs     : #fp-auth-accessory-name, #fp-auth-accessory-file.
 * Outputs    : #fp-auth-accessory-status (one line, success or error).
 * Constraints: The file is read client-side and never re-sent as anything
 *              but the one request it becomes; nothing here logs its bytes.
 *              A 409 offers "Replace existing" via the same window.confirm
 *              pattern timeline.js's history controls already use, and
 *              retries once with allow_overwrite=true — the field
 *              routes_auth.py now reads from either body shape (CF-P2-19).
 */
"use strict";

import { $ } from "./state.js";
import { api } from "./api.js";
import { t } from "./i18n.js";

function elements() {
  return {
    name: $("fp-auth-accessory-name"),
    file: $("fp-auth-accessory-file"),
    add: $("fp-auth-accessory-add"),
    status: $("fp-auth-accessory-status"),
  };
}

/**
 * The .json file's base64 key: a bare string, or one of the field names
 * accessories.py's own plist parser already accepts (`_parse_plist`).
 */
function extractPrivateKeyB64(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (_) {
    return text.trim(); // not JSON: the whole file is treated as the key
  }
  if (typeof parsed === "string") return parsed.trim();
  if (parsed && typeof parsed === "object") {
    return parsed.private_key_b64 || parsed.privateKey || parsed["Private Key"] || null;
  }
  return null;
}

/** POST the accessory: a .plist goes as multipart, everything else as JSON. */
async function submitAccessory(name, file, allowOverwrite) {
  if (file.name.toLowerCase().endsWith(".plist")) {
    const form = new FormData();
    form.set("name", name);
    form.set("plist", file);
    if (allowOverwrite) form.set("allow_overwrite", "true");
    return api("/api/apple/accessories", { method: "POST", body: form });
  }
  const key = extractPrivateKeyB64(await file.text());
  if (!key) throw new Error(t("auth.apple.accessories.badJson"));
  return api("/api/apple/accessories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, private_key_b64: key, allow_overwrite: allowOverwrite }),
  });
}

/** Submit once; on a 409, offer to replace and retry exactly once. */
async function submitWithRetry(name, file, status, nameEl, fileEl, allowOverwrite = false) {
  try {
    const record = await submitAccessory(name, file, allowOverwrite);
    status.textContent = t("auth.apple.accessories.added", { name: record.name });
    nameEl.value = "";
    fileEl.value = "";
  } catch (err) {
    if (err.message === "Locked") return;
    const canRetry = !allowOverwrite && err.status === 409;
    if (canRetry && window.confirm(t("auth.apple.accessories.confirmReplace", { name }))) {
      await submitWithRetry(name, file, status, nameEl, fileEl, true);
      return;
    }
    status.textContent = err.message;
  }
}

async function addAccessory() {
  const { name, file, add, status } = elements();
  const nameValue = name.value.trim();
  const chosen = file.files[0];
  if (!nameValue || !chosen) {
    status.textContent = t("auth.apple.accessories.pickBoth");
    return;
  }
  add.disabled = true;
  try {
    await submitWithRetry(nameValue, chosen, status, name, file);
  } finally {
    add.disabled = false;
  }
}

let mounted = false;

/** Wire the "Add accessory" button once; safe to call on every panel open. */
export function mountAccessoriesPanel() {
  if (mounted) return;
  $("fp-auth-accessory-add").addEventListener("click", addAccessory);
  mounted = true;
}

/** lock.js purgeRenderedData() hook, called from auth.js's own purge(). */
export function purgeAccessories() {
  const { name, file, status } = elements();
  name.value = "";
  file.value = "";
  status.textContent = "";
}
