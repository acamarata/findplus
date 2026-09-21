/*
 * Alerts tab: Telegram setup, webhook config, widget toggle.
 *
 * Purpose    : Surface E6's alerts backend in the dashboard. The rules table
 *              and add-rule dialog live in alerts_rules.js (split out at the
 *              PRI rule-7 300-line file cap); this module owns wiring them
 *              in, plus the two channel sections and the widget toggle.
 * Inputs     : GET/POST/PUT/DELETE under /api/alerts/*; GET /api/settings/
 *              widget.show_map.
 * Outputs    : The two channel sections inside #tab-alerts (static markup
 *              in index.html); rules table/dialog via alerts_rules.js.
 * Constraints: textContent only, never raw markup — API strings can never
 *              run as script. Bot token lives only in the fetch body, masked
 *              field clears on focus. Widget toggle: per-key GET/PUT/POST
 *              /api/settings/widget.show_map (matches app.start_at_login;
 *              build-notes.md § E10-S2); GET returns `{"widget.show_map": bool}`.
 */
"use strict";
import { $ } from "./state.js";
import { t } from "./i18n.js";
import { api } from "./api.js";
import {
  fillOptions,
  loadRules,
  openAddRuleDialog,
  renderRulesTable,
  saveRule,
  updateRuleTargetVisibility,
} from "./alerts_rules.js";
import { loadDeliveries, purgeDeliveries } from "./alerts_deliveries.js";
import {
  loadChannels,
  wireChannelControls,
  purgeChannels,
  showTelegramTokenPlaceholder,
} from "./alerts_channels.js";
const WIDGET_SETTING = "/api/settings/widget.show_map";
export function init() {
  wireStaticControls();
  injectLatencyFallback();
  // Mask the token field before refreshAll()'s GET lands (fire-and-forget
  // below): #fp-tg-token must never be observably empty while that fetch is
  // in flight (E13 loop3 L3-3). Awaiting refreshAll() here instead would
  // serialize an extra network round trip into main.js's boot chain, which
  // already awaits this init() call.
  showTelegramTokenPlaceholder();
  refreshAll();
}
export async function refreshAll() {
  // A 401 here already showed the lock screen; loadWidgetToggle() runs either way.
  try { await loadChannels(); await loadRules(); await loadDeliveries(); } catch (_) { /* locked or unreachable */ }
  await loadWidgetToggle();
  // init() fires this without awaiting it, so a test (or a fast user) can act
  // on the tab before the boot-time GETs it renders from have landed. This
  // marker is the deterministic "those renders are done" signal (E13 loop3
  // L3-1, matching R-P2-20's data-fp-ready convention) -- open_alerts_tab()
  // only proves the section exists, not that refreshAll() has run.
  $("fp-telegram-section").dataset.fpReady = "alerts";
}
function injectLatencyFallback() {
  const el = $("fp-alerts-latency-notice");
  if (el && !el.textContent) {
    el.textContent = t("honesty.alertsLatency");
  }
}
function wireStaticControls() {
  // Telegram/WhatsApp/webhook buttons are wired by alerts_channels.js itself
  // (loop1 split, findplus#238): this used to inline the same wiring against
  // that module's un-exported locals, which threw "saveWhatsapp is not
  // defined" on every boot and aborted main() before bootDashboard() ran
  // (loop1 regression, #tracks never rendered).
  wireChannelControls();
  $("fp-add-rule-btn").addEventListener("click", openAddRuleDialog);
  $("fp-rule-save").addEventListener("click", saveRule);
  $("fp-rule-cancel").addEventListener("click", () => $("fp-add-rule-dialog").close());
  $("fp-rule-target-device").addEventListener("change", updateRuleTargetVisibility);
  $("fp-rule-target-group").addEventListener("change", updateRuleTargetVisibility);
  wireWidgetToggle();
}
/* channels */
/* widget toggle */
async function loadWidgetToggle() {
  const toggle = $("fp-widget-map-toggle");
  if (!toggle) return;
  try {
    toggle.checked = (await api(WIDGET_SETTING))["widget.show_map"] === true;
  } catch (_) { /* locked at boot; a later refreshAll() after unlock repopulates it */ }
}
function wireWidgetToggle() {
  const toggle = $("fp-widget-map-toggle");
  if (!toggle) return;
  toggle.addEventListener("change", async (e) => {
    try {
      await api(WIDGET_SETTING, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: e.target.checked }),
      });
    } catch (_) { /* best-effort; the checkbox already reflects the choice */ }
  });
}
/** lock.js purgeRenderedData() hook: device/place names must not survive the lock screen. */
export function purge() {
  renderRulesTable([]);
  purgeDeliveries();
  purgeChannels();
  ["fp-rule-place", "fp-rule-device", "fp-rule-group"].forEach((id) => fillOptions($(id), [], () => []));
  // renderTelegramSection/renderWebhookSection above already blank the token
  // and URL inputs. These two nothing else touches: a typed webhook secret and
  // the add-rule dialog's name (a closed <dialog> keeps its input values, so
  // both stay readable from DevTools behind the lock screen).
  ["fp-rule-name", "fp-webhook-secret"].forEach((id) => {
    const el = $(id);
    if (el) el.value = "";
  });
  const err = $("fp-rule-error");
  if (err) err.textContent = "";
  const dlg = $("fp-add-rule-dialog");
  if (dlg && dlg.open) dlg.close();
}
