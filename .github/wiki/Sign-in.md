# Sign in

Find+ needs an account on at least one tracking network before it has anything
to poll. You can sign in from the dashboard, from the setup wizard, or from the
terminal. All three write the same credentials to `~/.findplus/`.

## Google

Open **Settings**. Sign-in is the first section of the dialog. Click **Sign in
with Google** and Find+ opens Chrome on Google's own sign-in page. The card
reports each stage as it runs: starting Chrome, waiting for you inside the
Chrome window, finishing up, then the account it captured.

Chrome runs in a profile directory of its own, `~/.findplus/chrome-profile`.
That directory holds the cookies and history of this sign-in only. Your personal
Chrome profile is not read, not written, and not closed. It is a separate
profile, not a sandbox: the browser still reaches the network the way any
browser does.

If Chrome is not installed, the button is disabled and the card says:

> Google Chrome was not found on this machine. Google sign-in drives Chrome
> directly and cannot run without it. Install it from
> https://www.google.com/chrome/ and try again.

The check re-runs on every poll of the sign-in job, so the message clears by
itself once you install Chrome.

What a Find Hub account gives you:

> This history consists of locations reported through Google's Find Hub
> network. Your trackers use nearby participating Android devices to report their
> location. Location updates can therefore be delayed, sparse, or
> unavailable, and this application should not be treated as real-time
> emergency or child-safety GPS tracking.

## Apple

The Apple card takes your Apple ID and password. If Apple wants a second
factor, the form is replaced by a code field and Apple sends the code to a
trusted device. Enter it and the sign-in completes.

Your Apple password is held only for the duration of that one sign-in call. It
is never written to disk, never logged, and never sent back to the browser. The
password and code fields are cleared the moment the request leaves.

What an Apple Find My account gives you:

> Apple Find My locations come from nearby Apple devices and can be delayed,
> sparse or unavailable. Find+ can only query accessories whose keys you hold;
> genuine AirTags require extracting pairing keys, which most users cannot do.

Accessory keys (extracted pairing keys for AirTags and other Find My
accessories) can be added from the terminal, the API, or the dashboard, and
work without an Apple ID sign-in. In Settings, under the Apple card, give the
accessory a name and pick its key file (a `.plist` export or a `.json` file
holding the base64 private key), then click **Add accessory**. If that name's
key is already registered, Find+ asks before replacing it. `findplus apple
add-accessory` takes the same plist or base64 key from the terminal, and
`findplus apple list` shows what is registered. The same thing is reachable
over the API at `POST /api/apple/accessories`.

## Security

Every sign-in route is loopback-only, like the rest of the API, and sits behind
the app lock: while Find+ is locked, `/api/auth/*` returns `401` the same way
every other data route does. Starting a sign-in also requires the request to
carry an `Origin` or `Sec-Fetch-Site` header, which browsers and the macOS app
always send.

## Command line

```bash
findplus auth
findplus auth --provider apple-find-my
findplus auth --status
findplus auth --status --json
```

`findplus auth` is the terminal-only flow and behaves the same as it always
has. `findplus auth --status` prints which providers you are signed in to, as
which account, and what is still missing; `--json` prints the same object the
dashboard reads from `GET /api/auth/status`.

Signing in is also step 2 of the [first-run wizard](First-run).

---
[[Home]]
