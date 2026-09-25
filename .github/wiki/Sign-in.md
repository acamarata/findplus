# Sign in

Find+ needs an account on at least one tracking network before it has anything
to poll. You can sign in from the dashboard, from the setup wizard, or from the
terminal. All three write the same credentials to `~/.findplus/`.

## Google

Open **Settings**. Sign-in is the first section of the dialog, and the setup
wizard shows the same two cards. Click **Connect Google Find Hub** and Find+
opens Chrome on Google's own sign-in page. You type your password there, not
into Find+. The card reports each stage as it runs: opening Chrome, waiting for
you to finish in the Chrome window, saving the session, then the account it
captured.

If the sign-in cannot start or does not finish, the card says why in plain
words and offers **Try again**. That covers an error from the Find+ service, a
service Find+ cannot reach, a sign-in that expired or ran past 5 minutes, and a
failure Chrome reported.

The buttons are Find+'s own, not Google's or Apple's sign-in buttons. Find+
does not use either company's sign-in service: it drives a Chrome sign-in for
Find Hub and an Apple ID sign-in for Find My, and it is not affiliated with
either company.

Chrome runs in a profile directory of its own, `~/.findplus/chrome-profile`.
That directory holds the cookies and history of this sign-in only. Your personal
Chrome profile is not read, not written, and not closed. It is a separate
profile, not a sandbox: the browser still reaches the network the way any
browser does.

If Chrome is not installed, the button is disabled and the card says:

> Google Chrome was not found on this machine. Google sign-in drives Chrome
> directly and cannot run without it. Install it from
> https://www.google.com/chrome/ and try again.

A **Download Google Chrome** link sits under it. Once Chrome is installed,
click **Check again**.

What a Find Hub account gives you:

> This history consists of locations reported through Google's Find Hub
> network. Your trackers use nearby participating Android devices to report their
> location. Location updates can therefore be delayed, sparse, or
> unavailable, and this application should not be treated as real-time
> emergency or child-safety GPS tracking.

## Apple

The Apple card takes your Apple ID and password; click **Connect Apple Find
My**. If Apple wants a second factor, the form is replaced by a code field.
Apple shows the code on one of your trusted Apple devices, or, when the account
has no trusted device, texts it to your phone and the card says so. Enter it
and click **Verify code**. A wrong code is named as such and the code field
stays; **Try again** starts over with a fresh form. `findplus auth --provider
apple-find-my` lists every method Apple offers and lets you pick one.

A pip install without the Apple extra cannot sign in to Apple at all. The card
then says so and names the fix, `pip install 'findplus[apple]'`, instead of
showing a form that could only fail.

Your Apple password is held in memory only until the sign-in finishes: until
Apple accepts the code, when it asks for one, because the library signs in
again with it after the code. An abandoned sign-in is dropped after 10
minutes. The password is never written to disk, never logged, and never sent
back to the browser. The password and code fields are cleared the moment the
request leaves.

`~/.findplus/apple-account.json` (mode 0600) holds your Apple ID and the
session tokens Apple issued. Because the password is not saved, Find+ cannot
quietly sign in again when Apple expires those tokens. Polls of your Apple
accessories then report that sign-in is needed, and you sign in again the same
way.

### Anisette

Apple expects every sign-in and location query to carry "anisette" headers,
the device identity a real Mac or iPhone sends. By default Find+ produces them
locally with FindMy.py's built-in engine. It needs no setup, but on the first
sign-in it downloads helper libraries (a few MB) from
`anisette.dl.mikealmel.ooo`, a server run by the author of the `anisette`
library, not by Apple or by Find+. It caches them in
`~/.findplus/anisette-libs.bin` and then registers a virtual device with
Apple. If that download or registration fails, the card says so before your
password is sent anywhere.

To use an anisette server you run yourself instead:

```bash
findplus config set APPLE_ANISETTE_URL http://127.0.0.1:6969
```

The choice is saved with the session, so change it before you sign in.

What an Apple Find My account gives you:

> Apple Find My locations come from nearby Apple devices and can be delayed,
> sparse or unavailable. Find+ can only query accessories whose keys you hold;
> genuine AirTags require extracting pairing keys, which most users cannot do.

Accessory keys (extracted pairing keys for AirTags and other Find My
accessories) can be added from the terminal, the API, or the dashboard before
or after you sign in, but Find+ can only locate them once an Apple ID is
signed in. In Settings, under the Apple card, give the accessory a name and
pick its key file (a decrypted Find My pairing `.plist`, a plist holding one
private key, or a `.json` file holding the base64 private key), then click
**Add accessory**. The accepted formats are listed under
[Providers](Providers). If that name's
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
