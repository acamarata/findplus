# Sign in

Find+ needs an account on at least one tracking network before it has anything
to poll. You can sign in from the dashboard, from the setup wizard, or from the
terminal. All three write the same credentials to `~/.findplus/`.

## Google

Open **Settings**. Sign-in is the first section of the dialog, and the setup
wizard shows the same two cards. The Google card offers two ways in. The first
uses the Chrome you already use and is the one to pick; the second lets Find+
open a Chrome window of its own.

### Sign in with your Chrome

Click **Sign in with your Chrome**. Find+ opens Google's own sign-in page,
`https://accounts.google.com/EmbeddedSetup`, as a normal tab of your Google
Chrome, and the card says where it opened it. Without Google Chrome, the page
opens in your default browser instead and the card says that; the steps below
are written for Chrome. The card then shows the same steps:

1. Sign in to your Google account in that Chrome tab, including any 2-step
   prompt. The page may look blank or keep spinning after you sign in. That is
   expected.
2. Open Chrome's developer tools: Option+Command+I on a Mac, Ctrl+Shift+I on
   Windows or Linux.
3. Go to the Application tab, then Storage > Cookies >
   `https://accounts.google.com`.
4. Click the `oauth_token` row and copy its Value. It starts with `oauth2_4/`.
5. Paste it into the card with your Google email, then click **Connect**.

Find+ checks the token with Google, saves the session and shows "Signed in as"
with your account. If Google refuses the token, the card says so in plain
words: "Google did not accept that token. It expires within minutes: sign in
again in Chrome and copy a fresh one." If Google cannot be reached, it says
that instead.

Why a copy step at all: Chrome 136 and later ignore the switches another
program needs to drive your everyday Chrome profile, so Find+ cannot automate
the browser you actually use. And Google issues the Find Hub token only to a
browser, as the `oauth_token` cookie that page sets after you sign in. So you
copy that one value across, once.

What happens to the token: Find+ exchanges it with Google right away for the
long-lived session Find Hub needs, then forgets it. It is never written to
disk, never logged and never sent back to the browser. The token field is
cleared the moment you click Connect. The token expires within minutes, so
copy it right after you sign in.

### Or let Find+ open its own Chrome window

The smaller button under the steps, **Or let Find+ open its own Chrome
window**, runs the older automatic flow. Find+ opens a separate Chrome window
on Google's sign-in page, waits for you to sign in there and picks the token
up itself. The card reports each stage as it runs: opening Chrome, waiting for
you to finish in the Chrome window, saving the session, then the account it
captured.

If that sign-in cannot start or does not finish, the card says why in plain
words and offers **Try again**. That covers an error from the Find+ service, a
service Find+ cannot reach, a sign-in that expired or ran past 5 minutes, and a
failure Chrome reported. A **Cancel** button appears the moment you click it,
while Find+ is opening Chrome and while it is waiting for you to finish signing
in, so you are never stuck waiting out the 5-minute timeout to back out.

That window runs in a profile directory of its own,
`~/.findplus/chrome-profile`. The directory holds the cookies and history of
this sign-in only. Your personal Chrome profile is not read, not written, and
not closed. It is a separate profile, not a sandbox: the browser still reaches
the network the way any browser does.

### Unlock encrypted locations

Google encrypts your Find Hub locations end to end. After you sign in, Find+
still needs to unlock that encryption once before it can read any tracker, and
the card shows an **Unlock encrypted locations** step until you do. It needs
your Android phone's screen lock (PIN, pattern or password): that is what
proves to Google you are allowed the key.

Click **Unlock encrypted locations**. Find+ opens a Chrome window of its own
and Google asks for your phone's screen lock in it. Enter it there. Find+ never
asks you to paste anything into a console, and it does not touch your everyday
Chrome. When the key is stored the step disappears and the next poll can
decrypt. A **Cancel** button backs out while it waits, and a failure is shown
with the step still there to try again.

Find+ stores the key (`shared_key`) in `~/.findplus/secrets.json` at mode 0600
and never logs it. From a terminal, `findplus auth --unlock` does the same:
it opens the window, waits for the screen lock, and stores the key.

If a poll ever reports that locations are locked again (for example after the
end-to-end data is reset on your account), the same step reappears; unlock once
more.

### Both ways

The buttons are Find+'s own, not Google's or Apple's sign-in buttons. Find+
does not use either company's sign-in service. The sign-in panel says so once,
under the cards: "Find+ is not affiliated with Apple or Google. Find Hub and
Find My are their trademarks."

A sign-in that fails or is cancelled part-way never shows as signed in: the
card counts you as signed in only once Find+ holds a Google session and the
account it belongs to.

If Chrome is not installed, the separate-window button is disabled and the
card says:

> Google Chrome was not found on this machine. Google sign-in drives Chrome
> directly and cannot run without it.

A **Download Google Chrome** link sits right under it. The notice does not
also print the raw URL, so there is one way to get Chrome, not two. Once
Chrome is installed, click **Check again**.

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

## Sign out

Once a card shows "Signed in as ...", a **Disconnect** button appears next to
it, on both the dashboard's Settings > Sign-in and the setup wizard. Clicking
it opens an inline confirm row (never a native browser popup) that says what
disconnecting does and does not do, then a second click carries it out.

Disconnecting **Google** removes Find+'s own copy of your Google credentials
(`~/.findplus/secrets.json`): the AAS/ADM tokens, FCM credentials and the
end-to-end owner key. Your Google account itself is untouched; nothing is
revoked on Google's side.

Disconnecting **Apple** removes the saved session (`~/.findplus/apple-account.json`).
Any accessory keys you registered (AirTags, other Find My trackers) are kept:
they are your own imported keys, not something Find+ generated for the
session, and they are what let Find+ keep decrypting that accessory's future
reports once you sign back in.

Either way, **tracked devices and their history stay**. Disconnecting only
removes the credential; it does not stop tracking a device, delete a place,
group or alert rule, or clear anything from the map. Sign in again any time to
resume seeing new locations for the same devices.

From the terminal:

```bash
findplus auth --sign-out --provider google-find-hub
findplus auth --sign-out --provider apple-find-my
```

or over the API, `DELETE /api/auth/google-find-hub` / `DELETE
/api/auth/apple-find-my` (loopback-only, behind the app lock, and requiring the
same `Origin`/`Sec-Fetch-Site` header the sign-in routes do).

## Security

Every sign-in route is loopback-only, like the rest of the API, and sits behind
the app lock: while Find+ is locked, `/api/auth/*` returns `401` the same way
every other data route does. Starting a sign-in also requires the request to
carry an `Origin` or `Sec-Fetch-Site` header, which browsers and the macOS app
always send.

The two routes behind "Sign in with your Chrome" are `POST
/api/auth/google/open` (opens the page, answers which browser got it) and
`POST /api/auth/google/token` with `{"email", "oauth_token"}`. Both carry the
same header requirement, and the token route never quotes the token back, even
in an error. The unlock step's routes (`POST
/api/auth/google/unlock/start`, `GET .../unlock/progress`, `POST
.../unlock/cancel`) carry the same header requirement.

## Command line

```bash
findplus auth --token
findplus auth --unlock
findplus auth
findplus auth --provider apple-find-my
findplus auth --status
findplus auth --status --json
findplus auth --sign-out --provider google-find-hub
```

`findplus auth --token` is the terminal version of "Sign in with your Chrome":
it offers to open Google's page in your Chrome, prints the same steps, then asks
for your email and the token (typed hidden). For a script, set
`FINDPLUS_OAUTH_TOKEN` instead and only the email is asked for. The token never
goes on the command line, so it stays out of your shell history. `findplus
auth` without `--token` is the terminal's automatic flow and behaves the same
as it always has. `findplus auth --unlock` runs the unlock step (above) from a
terminal: it opens Find+'s own Chrome window for your Android screen lock and
stores the encryption key. `findplus auth --status` prints which providers you are signed in to, as
which account, and what is still missing; `--json` prints the same object the
dashboard reads from `GET /api/auth/status`. `--sign-out` removes that
provider's credential and exits; see [Sign out](#sign-out) above for exactly
what it does and does not remove.

Signing in is also step 2 of the [first-run wizard](First-run).

---
[[Home]]
