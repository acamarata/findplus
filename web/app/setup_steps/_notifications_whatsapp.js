/*
 * The WhatsApp controls of the wizard's Notifications step.
 *
 * Purpose    : Offer WhatsApp inline exactly like Telegram (R-P2-28 point 3) —
 *              phone, API key, Send test and Save through the same
 *              PUT/DELETE /api/alerts/channels/whatsapp routes the Alerts tab
 *              uses (alerts.js), rather than only a "configure later" link
 *              (loop-2 F3 / visual gate W4 F4). Simple Telegram/WhatsApp setup
 *              in the wizard is the owner's stated goal for this step.
 * Inputs     : ctx (for api()), the channel section element, and the
 *              channel's own state from GET /api/alerts/channels
 *              ({configured, phone_masked}).
 * Outputs    : PUT /api/alerts/channels/whatsapp on Save; POST /api/alerts/test
 *              on Send test.
 * Constraints: Own file for the same reason _notifications_telegram.js is:
 *              alerts.js's copy of this flow reads elements inside
 *              #app-shell, which is hidden while the wizard is open. Neither
 *              field is prefilled with a masked value on load — `phone_masked`
 *              is not a value the PUT would accept back, and the apikey has no
 *              masked form in the API contract at all (matches alerts.js's own
 *              renderWhatsappSection comment). Save clears the field's masked
 *              class BEFORE reading it, so the placeholder bullets can never
 *              be sent as the key (CR-C-E10 F1's fix, reused here). The saved
 *              status line shows the response's masked phone_masked, never the
 *              plaintext value just typed (loop2 B5, PII per R-P2-27.6).
 */
"use strict";

import { t } from "../i18n.js";

/** UAT7-N11: phone and API key had a placeholder as their only name, gone the
 * moment a value is typed. Wraps `input` with a real, always-visible
 * `<label for>` instead, reusing the sign-in step's own
 * `.fp-signin-field`/`.fp-signin-label` pair (same helper
 * _notifications_telegram.js defines for its own fields). */
function labeledField(id, labelText, input) {
  const wrap = document.createElement("div");
  wrap.className = "fp-signin-field";
  const label = document.createElement("label");
  label.className = "fp-signin-label";
  label.htmlFor = id;
  label.textContent = labelText;
  wrap.append(label, input);
  return wrap;
}

function clearMaskedToken(el) {
  if (el.classList.contains("fp-token-masked")) {
    el.value = "";
    el.classList.remove("fp-token-masked");
  }
}

function buildApikeyInput(configured) {
  const apikey = document.createElement("input");
  apikey.type = "password";
  apikey.id = "fp-setup-wa-apikey";
  apikey.placeholder = t("alerts.whatsapp.apikey");
  apikey.addEventListener("focus", () => clearMaskedToken(apikey));
  apikey.value = configured ? "••••••••" : "";
  apikey.classList.toggle("fp-token-masked", configured);
  return apikey;
}

/** PUT the credentials, then show the PUT response's own masked phone --
 * never the plaintext value just typed (loop2 B5). */
function wireSave(save, phone, apikey, status, ctx) {
  save.addEventListener("click", async () => {
    clearMaskedToken(apikey);
    const phoneVal = phone.value.trim();
    const apikeyVal = apikey.value.trim();
    if (!phoneVal || !apikeyVal) {
      (phoneVal ? apikey : phone).focus();
      return;
    }
    try {
      const result = await ctx.api("/api/alerts/channels/whatsapp", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: phoneVal, apikey: apikeyVal }),
      });
      phone.value = "";
      apikey.value = "••••••••";
      apikey.classList.add("fp-token-masked");
      const masked = result && result.whatsapp && result.whatsapp.phone_masked;
      status.textContent = t("alerts.whatsapp.connected", { phone: masked || phoneVal });
    } catch (err) {
      status.textContent = err.message;
    }
  });
}

function wireTest(test, status, ctx) {
  test.addEventListener("click", async () => {
    try {
      const result = await ctx.api("/api/alerts/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel: "whatsapp" }),
      });
      status.textContent =
        result.status === "sent"
          ? t("alerts.testSent")
          : t("alerts.testFailed", { error: result.error || t("common.unknownError") });
    } catch (err) {
      status.textContent = t("alerts.testFailed", { error: err.message });
    }
  });
}

export function whatsappControls(section, value, ctx) {
  const configured = !!(value && value.configured);
  const phone = document.createElement("input");
  phone.type = "text";
  phone.id = "fp-setup-wa-phone";
  phone.placeholder = t("alerts.whatsapp.phonePlaceholder");
  // UAT7-N11: a real, visible label instead of an aria-label that vanished
  // along with the placeholder once typed into (UAT3 N26). Same wording the
  // Settings tab's own <label> shows for this field (web/partials/alerts.html),
  // so a screen reader and a sighted Settings user hear/read the same thing.
  const phoneField = labeledField(phone.id, t("alerts.whatsapp.phone"), phone);
  const apikey = buildApikeyInput(configured);
  const apikeyField = labeledField(apikey.id, t("alerts.whatsapp.apikey"), apikey);

  const status = document.createElement("p");
  status.className = "modal-note";
  if (configured && value.phone_masked) {
    status.textContent = t("alerts.whatsapp.connected", { phone: value.phone_masked });
  }

  const save = document.createElement("button");
  save.type = "button";
  save.id = "fp-setup-wa-save";
  save.className = "btn";
  save.textContent = t("alerts.whatsapp.save");
  wireSave(save, phone, apikey, status, ctx);

  const test = document.createElement("button");
  test.type = "button";
  test.id = "fp-setup-wa-test";
  test.className = "btn btn-secondary";
  test.textContent = t("alerts.whatsapp.test");
  wireTest(test, status, ctx);

  // UAT3 N26: Save and Send test sat flush against each other with no gap.
  // Reuses the same .fp-alerts-actions (gap: 8px) the Settings tab's own
  // WhatsApp actions row already uses (web/partials/alerts.html), rather
  // than a second gap rule for the same pair of buttons.
  const actions = document.createElement("div");
  actions.className = "fp-alerts-actions";
  actions.append(save, test);

  section.append(phoneField, apikeyField, actions, status);
}
