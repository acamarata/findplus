# Places and Alerts

## Places

A place is a named circle on the map with a configurable radius (20 m to 5000 m). Find+
monitors whether each tracked tag is inside or outside each place by applying the geofence
engine to incoming location fixes. Confirmations are required before emitting an enter or
exit event, which reduces false alerts from location jitter.

## Alert rules

An alert rule ties a place, a device or group, and a notification channel (Telegram or
webhook). When a qualifying enter or exit event is confirmed, Find+ sends a notification. A
cooldown period (default 30 minutes) prevents repeated alerts for the same tag at the same
place. Delivery is best-effort: a failed send is recorded in the alert log and is not
retried, and a failed send never starts the cooldown on its own.

## Privacy: outbound connections

Find+ connects to the following external services during normal operation:

- The location network (Google Find Hub or Apple Find My) to poll for tag updates.
- api.telegram.org -- only when Telegram is configured as an alert channel.
- Your webhook URL -- only when a webhook is configured.

Map tiles are loaded by your browser directly from OpenStreetMap tile servers. The Find+
daemon does not proxy or log tile requests.

## Delivery log

The Alerts tab lists what Find+ actually sent, most recent first:

| Column | What it holds |
|---|---|
| Rule | The rule that matched, by name. |
| Channel | `telegram` or `webhook`, from the rule. |
| Kind | `device` for a single tracker, `group` for a quorum crossing. |
| Sent | When the attempt was made, in your local time. |
| Status | `sent`, `failed`, or `skipped`. |
| Error | Why it failed, or why it was skipped. |

`skipped` means the rule matched but nothing was sent — most often because the
rule names a channel with no credentials, such as a Telegram rule created
before setup finished, or one left enabled after the Telegram connection was
deleted. A skipped or failed delivery does not start the rule's cooldown, so
the next crossing is still eligible.

Errors are stored with credentials masked. A webhook that carries its key in
the query string will show the URL with that value replaced.

## Alert latency

Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late.

Google Find Hub and Apple Find My report locations through nearby participating devices. A
tag that has not passed near a participating device will not report until it does. Find+
sends the alert as soon as the fix arrives; the delay is in the network, not in Find+.

## Webhook payload

A webhook alert POSTs a JSON body with `event`, `kind`, `subject`, `place`, `observed_at`,
`fetched_at`, `lag_minutes`, `confidence`, `note`, and `sent_at`. `lag_minutes` is the delay
between `observed_at` and `fetched_at` in minutes -- it is `null`, never `0`, whenever the
fetch time isn't known (every group alert, since a group crossing has no single fetch time,
and any device alert whose fetch time wasn't recorded). Treat `null` as "delay unknown," not
as "delivered instantly." A `X-FindPlus-Signature` header (HMAC-SHA256 of the body) is added
when a webhook secret is configured.

## Telegram setup walkthrough

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and follow the
   prompts to get a bot token.
2. Open the dashboard's Alerts tab, paste the token into **Bot token**, and click **Connect**.
3. Send any message to your new bot within 120 seconds. The dashboard waits for it and
   confirms the chat once it arrives.
4. Click **Send test** to confirm delivery. The bot token is never shown again in full: the
   field only ever displays its last four characters.

The token lives in `~/.findplus/alerts.json` (mode `0600`), never in the database or logs.

## WhatsApp

WhatsApp-native alerts are planned for Find+ v1.1. The webhook channel is the interim path
for connecting Find+ to messaging services that support incoming webhooks, including
WhatsApp via a Business API provider. See the Webhook setup page for an example
configuration.
