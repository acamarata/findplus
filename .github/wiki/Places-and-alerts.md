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
place.

## Privacy: outbound connections

Find+ connects to the following external services during normal operation:

- The location network (Google Find Hub or Apple Find My) to poll for tag updates.
- api.telegram.org -- only when Telegram is configured as an alert channel.
- Your webhook URL -- only when a webhook is configured.

Map tiles are loaded by your browser directly from OpenStreetMap tile servers. The Find+
daemon does not proxy or log tile requests.

## Alert latency

Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late.

Google Find Hub and Apple Find My report locations through nearby participating devices. A
tag that has not passed near a participating device will not report until it does. Find+
sends the alert as soon as the fix arrives; the delay is in the network, not in Find+.

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
