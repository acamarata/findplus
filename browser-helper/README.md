# Find+ helper for Chrome

A small, open-source browser extension that connects your Google Find Hub
account to a [Find+](https://github.com/acamarata/findplus) install running on
the same computer. It is part of the Find+ project and shares its licence
(GPL-3.0-or-later).

## Why an extension is needed

Google hands the Find Hub sign-in token and the end-to-end encryption keys only
to a browser page, and Chrome 136 and later refuse to let another program drive
your everyday Chrome profile. So Find+ cannot read them for you. This helper,
running inside your own Chrome, passes those two values from Google's own pages
to Find+ on your machine, so signing in feels like any other "Sign in with
Google" button instead of asking you to copy things by hand.

## What it can see, and what it cannot

- **Reads** the `oauth_token` cookie that `accounts.google.com` sets after you
  sign in, and the encryption vault keys that Google's unlock page produces
  after your Android screen-lock check. It reads them only while Find+ has
  started a sign-in or unlock and asked the helper to listen.
- **Sends** them only to Find+ at `http://127.0.0.1` on this computer, with a
  single-use token Find+ generated. Find+ exchanges the sign-in token with
  Google immediately and never stores it.
- **Cannot** reach any other website. Its host permissions are exactly
  `accounts.google.com` and `127.0.0.1:8647`; there is no server, no analytics and
  no remote code. Read every line here to confirm it.

It does not touch your Google password, which you type on Google's own page.

## Permissions

- `cookies` — to read the one `oauth_token` cookie on `accounts.google.com`.
- `storage` — to remember, in session storage only, that a Find+ sign-in is in
  progress.
- host access to `https://accounts.google.com/*` and `http://127.0.0.1:8647/*` (the Find+ port only, not every local port).

## Install (one time)

1. In Find+, open **Settings > Sign-in** and use **Show helper folder** to
   reveal this extension on disk (or use this `browser-helper/` folder from a
   checkout).
2. Open `chrome://extensions` in Google Chrome.
3. Turn on **Developer mode** (top right).
4. Click **Load unpacked** and choose the folder.

The extension ID is fixed by the public key in `manifest.json`:

```
gegkceilnmbifdpmipcikkgnmdhpkedo
```

Find+ accepts the helper's messages only from that exact ID.

## Files

- `manifest.json` — Manifest V3, the pinned public key, permissions.
- `helper_core.js` — pure logic (which cookie counts, which endpoint); unit-tested.
- `background.js` — the service worker: the cookie listener and the two POSTs.
- `content_begin.js` — on Find+'s begin page: marks it and hands over the state.
- `content_unlock_main.js` / `content_unlock_bridge.js` — the unlock-page hook
  and the gated bridge to the worker.

## Building a packed version

Loading unpacked needs no private key. A packed `.crx` would; that private key
is never committed. The public key in `manifest.json` is what fixes the ID.
