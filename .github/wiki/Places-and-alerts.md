# Places and Alerts

## Places

A place is a named circle on the map with a configurable radius (20 m to 5000 m). Find+
monitors whether each tracked tag is inside or outside each place by applying the geofence
engine to incoming location fixes. Confirmations are required before emitting an enter or
exit event, which reduces false alerts from location jitter.

The Places tab's side panel lists every saved place -- its color, its radius, and which
tracked devices are inside it right now -- with Edit and Delete on each row and a click
anywhere else on the row to centre the map on that place.

## Alert rules

An alert rule ties a place, a device or group, and one or more notification channels
(Telegram, webhook, WhatsApp, or Mac notifications). A rule may target more than one channel
at once: the rule form uses checkboxes, not a single dropdown, and each ticked channel is
delivered and cooled down on its own. Telegram itself can notify more than one chat: the
Telegram card's Targets field takes a comma-separated list of chat ids or @usernames, so one
rule can message a group, a specific person, or several people at once (up to 10 targets).
Each target is delivered and retried on its own, so one person's blocked bot or a bad id
never holds up the rest. When a qualifying enter or exit event is confirmed,
Find+ sends a notification. A
cooldown period (default 30 minutes) prevents repeated alerts for the same tag at the same
place. Delivery is best-effort: a failed send is recorded in the alert log, and a failed or
skipped send never starts the cooldown on its own. A failure that looks temporary -- a
timeout, a "too many requests" response, or the channel's server erroring out -- is retried
automatically, up to three more times at one minute, five minutes, then thirty minutes after
the first failure. A rejected request (a bad credential, a malformed number, anything the
channel refused outright) is not retried, and Mac notifications are never retried; they are
a one-time queue entry for the app to pick up, not a send that can fail this way.

## Privacy: outbound connections

Find+ connects to the following external services during normal operation:

- The location network (Google Find Hub or Apple Find My) to poll for tag updates.
- api.telegram.org -- only when Telegram is configured as an alert channel.
- Your webhook URL -- only when a webhook is configured.
- api.callmebot.com -- only when WhatsApp is configured as an alert channel; it carries the
  phone number and API key needed to relay the message, as described under WhatsApp below.
- OpenStreetMap's Nominatim geocoder -- only when you type an address into the place
  dialog and press Search. The daemon makes this request itself (not your browser), so
  your search text never reaches Nominatim without your pressing Search, and the request
  carries a Find+ User-Agent rather than your browser's. See "Address search" below.

Map tiles are loaded by your browser directly from OpenStreetMap tile servers. The Find+
daemon does not proxy or log tile requests.

## Places: default map view and address search

A first-time Places tab, or the setup wizard's own Places step, opens the map fit to your
tracked devices' latest known fixes; if none has ever reported yet, it fits your saved
places instead; if there are none of those either, it shows a plain world view rather than
guessing a location. "Add place" opens the dialog with the map's current centre already
filled in -- no map click is required, so the dialog and the whole flow are reachable by
keyboard alone.

Inside the dialog, "Use a tracker's last location" fills the coordinates from any one
tracked device's most recent fix. Address search is opt-in: typing in the search box does
nothing on its own, and only pressing Search sends that text to OpenStreetMap's Nominatim
service (nominatim.org), a third party not affiliated with Find+. Nominatim's own usage
policy caps Find+ at one request per second and asks for a descriptive User-Agent, both of
which the daemon enforces on every search.

## Delivery log

The Alerts tab lists what Find+ actually sent, most recent first:

| Column | What it holds |
|---|---|
| Rule | The rule that matched, by name. |
| Channel | `telegram`, `webhook`, `whatsapp` or `native`, from the rule. A rule with several channels gets one row per channel. |
| Target | Which chat this row went to, for Telegram (a rule with several targets gets one row per target). Blank for every other channel. |
| Kind | `device` for a single tracker, `group` for a quorum crossing. |
| Text | The notification's first line, rendered fresh on every read. Mac notifications only; every other channel shows a dash. |
| Body | The place and the observed/lag line beneath it. Mac notifications only. |
| Sent | When the first attempt was made, in your local time. |
| Status | `sent`, `failed`, `skipped`, `retrying`, `queued` or `delivered`. |
| Error | Why it failed, or why it was skipped. |

`skipped` means the rule matched but nothing was sent, most often because the
rule names a channel with no credentials, such as a Telegram rule created
before setup finished, or one left enabled after the Telegram connection was
deleted. A skipped or failed delivery does not start the rule's cooldown, so
the next crossing is still eligible.

`retrying` means the first attempt failed with something that looks
temporary, and Find+ will try again automatically; the Status column also
shows which attempt is next and when (for example "Retrying (attempt 2 of 4,
next at 14:35)"). If every retry fails, the row's status becomes `failed`
and says "Failed after 4 attempts" instead of a bare `failed`, so you can
tell a delivery that exhausted its retries from one that never qualified
for one.

`queued` and `delivered` only appear on native (Mac notification) rows: `queued` means
the desktop app has not shown it yet, and `delivered` means it has -- neither is a network
send that can fail or retry, just a one-time entry waiting to be picked up.

Errors are stored with credentials masked. A webhook that carries its key in
the query string will show the URL with that value replaced.

## Alert latency

Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late.

Google Find Hub and Apple Find My report locations through nearby participating devices. A
tag that has not passed near a participating device will not report until it does. Find+
sends the alert as soon as the fix arrives; the delay is in the network, not in Find+.

The alert text itself (Telegram, native and the Delivery log's Text/Body columns) shows the
observed and reported times in your machine's local time with its zone abbreviation, for
example "14:35 EDT", not UTC.

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
   confirms the chat once it arrives -- this sets one target automatically.
4. Click **Send test** to confirm delivery. The bot token is never shown again in full: the
   field only ever displays its last four characters.

### Notifying more than one chat

The Telegram card has its own **Targets** field, separate from the bot token: a
comma-separated list of chat ids or @usernames -- your own user id, a group, or several
people at once. Find+ accepts up to 10 targets per rule.

- A numeric id, like `123456789` for a person or `-1001234567890` for a group or
  supergroup (the id is negative once Telegram promotes a group to a supergroup).
- An `@username`, for a public chat or a person who has set one.

To find a chat's id without knowing it by hand:

1. Message the bot directly, or add it to a group and send any message there. The bot
   must be a member of a group before it can post there, and it must have received at
   least one message first -- Telegram has no way to post into a chat it has never heard
   from.
2. Click **Find chat IDs**. Find+ asks the Bot API for the bot's own recent updates (never
   the token itself) and lists every chat it has seen, with its name and type.
3. Click **Add** next to a chat to append its id to the Targets field, then **Save
   targets**.

You can also type ids or usernames into the Targets field directly and click **Save
targets**, with no need to message the bot at all if you already know them. **Send test**
sends to every target and reports each one's own result, so a typo in one id never hides
whether the rest went through.

Targets set before this release keep working unchanged: a single stored chat id is read the
same way a comma list is, with no action needed.

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
   WhatsApp card, and click **Save**.
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
