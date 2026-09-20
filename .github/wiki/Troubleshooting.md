# Troubleshooting

## 1. Chrome closed by auth

The Google sign-in flow runs `pkill -f chrome` before launching its own
controlled Chrome window, so any Chrome windows you have open will be
closed. Save your work first, then rerun `findplus auth`.

## 2. 409 on Telegram

A `409 Conflict` from the Telegram API means another process (or another
bot) already holds the long-poll connection for that token. Use a different
bot token, or remove the webhook set on the existing bot in
[@BotFather](https://t.me/BotFather) (`/deletewebhook`) before retrying.

## 3. Port already in use

If `findplus serve` or `findplus start` cannot bind port 8647, change it:

```bash
findplus config set port 8648
findplus restart
```

## 4. Gatekeeper blocks Find+.app

macOS refuses to open the app because it is not notarised through the Mac
App Store. Right-click Find+.app and choose **Open** on first launch only;
subsequent launches work normally.

## 5. Why is my alert 40 minutes late?

Alerts inherit the network's delay. An arrival or departure may be reported
minutes to hours late.

This is not a Find+ bug. Google Find Hub and Apple Find My report locations
through nearby participating devices in a crowdsourced network, not a
direct GPS link. A tag reports as soon as some other device on the network
sees it. Find+ sends the alert the moment the fix arrives; the delay
happens upstream, in the network.

> This history consists of locations reported through Google's Find Hub
> network. Moto Tag uses nearby participating Android devices to report its
> location. Location updates can therefore be delayed, sparse, or
> unavailable, and this application should not be treated as real-time
> emergency or child-safety GPS tracking.

Apple Find My locations come from nearby Apple devices and can be delayed,
sparse or unavailable.


## 6. "Database not migrated. Run findplus db upgrade."

Every API call returns HTTP 503 with this message. The database file exists but
its schema is older than the code — usually after installing a new version
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
