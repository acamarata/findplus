# Places and Alerts

## Places

A place is a named circle on the map with a configurable radius (20 m to 5000 m). Find+
monitors whether each tracked tag is inside or outside each place by applying the geofence
engine to incoming location fixes. Confirmations are required before emitting an enter or
exit event, which reduces false alerts from location jitter.

## Alert rules

An alert rule ties a place, a device or group, and one or more notification channels
(Telegram, webhook, WhatsApp, or Mac notifications). A rule may target more than one channel
at once: the rule form uses checkboxes, not a single dropdown, and each ticked channel is
delivered and cooled down on its own. When a qualifying enter or exit event is confirmed,
Find+ sends a notification. A
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
| Channel | `telegram`, `webhook`, `whatsapp` or `native`, from the rule. A rule with several channels gets one row per channel. |
| Kind | `device` for a single tracker, `group` for a quorum crossing. |
| Text | The notification's first line, rendered fresh on every read. Mac notifications only; every other channel shows a dash. |
| Body | The place and the observed/lag line beneath it. Mac notifications only. |
| Sent | When the attempt was made, in your local time. |
| Status | `sent`, `failed`, or `skipped`. |
| Error | Why it failed, or why it was skipped. |

`skipped` means the rule matched but nothing was sent, most often because the
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

WhatsApp alerts go out through CallMeBot, which hands out a personal API key
over WhatsApp itself. Set it up from the Alerts tab, which carries the same
instructions:

1. Add +34 623 91 22 04 to your phone's contacts.
2. Send that contact "I allow callmebot to send me messages" from your own
   WhatsApp.
3. CallMeBot replies with an API key within about two minutes.
4. Paste your phone number in E.164 form and the API key into the Alerts tab's
   WhatsApp card, and click **Connect**.
5. Click **Send test** to confirm delivery.

WhatsApp alerts are relayed through CallMeBot, a third-party free service. Your alert
text transits CallMeBot's servers before reaching WhatsApp. Delivery is best-effort with
no guarantee. Find+ is not affiliated with WhatsApp, Meta or CallMeBot.

The API key is never sent back to the browser and the number is shown masked.
Both live in `~/.findplus/alerts.json` (mode `0600`). From the terminal:
`findplus alerts whatsapp set --phone +34... --apikey ...` and
`findplus alerts whatsapp clear`.

## Native notifications (macOS)

The Find+ menu bar app polls the daemon for new alert deliveries every 15
seconds and shows each one as an ordinary macOS notification, so an alert
arrives with no dashboard window open. This channel is macOS only in 1.1; on
Linux and Windows the option is not offered at all.

By default the banner says only "Find+ alert", because a notification preview
can appear on a locked screen. Turn on notification details in Settings to name
the person and the place instead. See [Settings](Settings) for the exact
wording and what it costs you.

Notifications are held while Find+ is locked. Unlock to see what you missed.

## Signing in from the dashboard

Open **Settings**; sign-in is the first section. The Google card starts the
Chrome sign-in and reports each stage as it runs; if Chrome is not installed it
says so and offers a download link instead of failing silently. The Apple card
takes your Apple ID and password, then asks for the code Apple sends to a
trusted device. Your Apple password is used for that one call and is never
stored, logged or returned.
