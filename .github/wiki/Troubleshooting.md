# Troubleshooting

## 1. Chrome closed by auth

Only the terminal's automatic Google flow (`findplus auth` without `--token`)
does this. It runs `pkill -f chrome` before launching its own controlled Chrome
window, so any Chrome windows you have open will be closed. Save your work
first, then rerun `findplus auth`. The dashboard no longer starts that flow
(the Find+ app signs in inside its own window), and `findplus auth --token` and
"Sign in with your Chrome" close nothing: they open Google's page as a tab of
your own Chrome and you paste the token back ([Sign in](Sign-in)).

## 2. "Locations are locked" after signing in

Google encrypts Find Hub locations end to end, so a fresh sign-in cannot decrypt
anything until you unlock the key once. Open **Settings > Sign-in** (or the setup
wizard) and use **Unlock encrypted locations**: Google asks for your Android phone's
screen lock in the Find+ sign-in window. From a terminal, run
`findplus auth --unlock`. The step disappears once the key is stored, and polls
decrypt from then on. Find+ never asks you to paste anything into a console.

## 2b. "This browser or app may not be secure", or a Find+ prompt to sign in again

If the sign-in window shows that message, Google refused it. Use the Chrome
helper or paste the cookie instead; see [Sign in](Sign-in#if-the-window-is-blocked).
If the menu bar or a banner says Find+ needs you, Google or Apple ended the
sign-in (often after a password change). Click the item or the banner's
**Sign in again** button and finish the window. Your history is kept. More in
[Sign in](Sign-in#when-a-sign-in-stops-working).

## 3. 409 on Telegram

A `409 Conflict` from the Telegram API means another process (or another
bot) already holds the long-poll connection for that token. Use a different
bot token, or remove the webhook set on the existing bot in
[@BotFather](https://t.me/BotFather) (`/deletewebhook`) before retrying.

## 4. Port already in use

If `findplus serve` or `findplus start` cannot bind port 8647, change it:

```bash
findplus config set port 8648
findplus restart
```

## 5. Gatekeeper blocks Find+.app

macOS refuses to open the app because it is not notarised through the Mac
App Store. Right-click Find+.app and choose **Open** on first launch only;
subsequent launches work normally.

## 6. Why is my alert 40 minutes late?

Alerts inherit the network's delay. An arrival or departure may be reported
minutes to hours late.

This is not a Find+ bug. Google Find Hub and Apple Find My report locations
through nearby participating devices in a crowdsourced network, not a
direct GPS link. A tag reports as soon as some other device on the network
sees it. Find+ sends the alert the moment the fix arrives; the delay
happens upstream, in the network.

> This history consists of locations reported through Google's Find Hub
> network. Your trackers use nearby participating Android devices to report their
> location. Location updates can therefore be delayed, sparse, or
> unavailable, and this application should not be treated as real-time
> emergency or child-safety GPS tracking.

Apple Find My locations come from nearby Apple devices and can be delayed,
sparse or unavailable.


## 7. "Database not migrated. Run findplus db upgrade."

Every API call returns HTTP 503 with this message. The database file exists but
its schema is older than the code, usually after installing a new version
without starting the daemon, which normally migrates on start.

Run the command it names:

```bash
findplus db upgrade
```

The daemon fails closed here on purpose. Answering "not locked" because the
settings table was missing would have opened every gated route, so an
unmigrated database is refused rather than guessed at.

---
[[Home]]
