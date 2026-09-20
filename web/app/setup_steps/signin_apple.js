/*
 * The Apple Find My branch of the wizard's sign-in step.
 *
 * Purpose    : Apple ID and password, then the 2FA code field the server asks
 *              for, driving POST /api/auth/apple/start -> /code and the
 *              progress poll between them (specs/onboarding.md § 4 row 2).
 * Inputs     : ctx (api/postJson), the step's status element, a Poller.
 * Outputs    : { form, codeRow, open() } for signin.js to place and reveal.
 * Constraints: The password is sent once and cleared from the field straight
 *              after; it is never stored, echoed or re-read.
 */
"use strict";

import { t } from "../i18n.js";
import { Poller, button, field } from "./_signin_dom.js";

/**
 * Build the Apple form and its code row, already wired.
 *
 * Both start hidden: open() reveals the credentials form, and the code row
 * appears only once the server reports `needs_2fa`.
 */
export function buildAppleBranch(ctx, status) {
  const poller = new Poller(status);
  const appleId = field("setup.signin.apple_id", "text");
  const password = field("setup.signin.password", "password");
  const code = field("setup.signin.code", "text");

  const codeSubmit = button("setup.signin.submit", () => {});
  const codeRow = document.createElement("div");
  codeRow.id = "fp-setup-apple-code";
  codeRow.hidden = true;
  codeRow.append(code.label, codeSubmit);

  function submitCode(jobId) {
    ctx.postJson("/api/auth/apple/code", { job_id: jobId, code: code.input.value.trim() })
      .then((result) => {
        codeRow.hidden = true;
        status.textContent = result.message;
      })
      .catch((err) => {
        status.textContent = err.message;
      });
  }

  function watch(jobId) {
    poller.start(ctx, "/api/auth/apple/progress", jobId, (progress) => {
      status.textContent = progress.message;
      if (progress.state === "needs_2fa") {
        poller.stop();
        codeRow.hidden = false;
        codeSubmit.onclick = () => submitCode(jobId);
      } else if (progress.state === "done" || progress.state === "failed") {
        poller.stop();
      }
    });
  }

  const submit = button("setup.signin.submit", () => {
    status.textContent = t("setup.signin.starting");
    ctx.postJson("/api/auth/apple/start", {
      apple_id: appleId.input.value.trim(),
      password: password.input.value,
    })
      .then(({ job_id: jobId }) => {
        password.input.value = "";
        watch(jobId);
      })
      .catch((err) => {
        password.input.value = "";
        // 409 carries the id of the sign-in already running; rejoin it rather
        // than leaving the user stuck at a conflict message (CR-C-E10 F1).
        if (err.status === 409 && err.body && err.body.job_id) {
          watch(err.body.job_id);
          return;
        }
        status.textContent = err.message;
      });
  });

  const form = document.createElement("div");
  form.id = "fp-setup-apple-form";
  form.hidden = true;
  form.append(appleId.label, password.label, submit);

  return {
    form,
    codeRow,
    open() {
      form.hidden = false;
    },
    stop() {
      poller.stop();
    },
  };
}
