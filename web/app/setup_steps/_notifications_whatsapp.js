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
 *              be sent as the key (CR-C-E10 F1's fix, reused here).
 */
"use strict";

import { t } from "../i18n.js";

function clearMaskedToken(el) {
  if (el.classList.contains("fp-token-masked")) {
    el.value = "";
    el.classList.remove("fp-token-masked");
  }
}

export function whatsappControls(section, value, ctx) {
  const phone = document.createElement("input");
  phone.type = "text";
  phone.id = "fp-setup-wa-phone";
  phone.placeholder = t("alerts.whatsapp.phonePlaceholder");

  const apikey = document.createElement("input");
  apikey.type = "password";
  apikey.id = "fp-setup-wa-apikey";
  apikey.placeholder = t("alerts.whatsapp.apikey");
  apikey.addEventListener("focus", () => clearMaskedToken(apikey));

  const configured = !!(value && value.configured);
  apikey.value = configured ? "••••••••" : "";
  apikey.classList.toggle("fp-token-masked", configured);

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
  save.addEventListener("click", async () => {
    clearMaskedToken(apikey);
    const phoneVal = phone.value.trim();
    const apikeyVal = apikey.value.trim();
    if (!phoneVal || !apikeyVal) {
      (phoneVal ? apikey : phone).focus();
      return;
    }
    try {
      await ctx.api("/api/alerts/channels/whatsapp", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: phoneVal, apikey: apikeyVal }),
      });
      phone.value = "";
      apikey.value = "••••••••";
      apikey.classList.add("fp-token-masked");
      status.textContent = t("alerts.whatsapp.connected", { phone: phoneVal });
    } catch (err) {
      status.textContent = err.message;
    }
  });

  const test = document.createElement("button");
  test.type = "button";
  test.id = "fp-setup-wa-test";
  test.className = "btn btn-secondary";
  test.textContent = t("alerts.whatsapp.test");
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

  section.append(phone, apikey, save, test, status);
}
