# Sign in

Find+ needs an account on at least one tracking network before it has anything
to poll. You can sign in from the dashboard, from the setup wizard, or from the
terminal. All three write the same credentials to `~/.findplus/`. You can
connect Google, Apple, or both, in any order.

## Google

Open **Settings**. Sign-in is the first section of the dialog, and the setup
wizard shows the same card. In the Find+ app, the card has one button.

### In the Find+ app: the sign-in window

1. Click **Connect**. A small window titled "Find+ sign-in: Google" opens. It
   shows Google's own sign-in page, and the title names the page you are on so
   you can check where you type your password.
2. Sign in as you normally would, including any 2-step prompt. The card behind
   it says "Finish signing in in the Find+ window."
3. When Google accepts you, the window closes by itself. The card says
   **Connected as** your account.

If you would rather stop, click **Cancel** on the card, or close the window
(Command+W). Nothing changes and the card says "Cancelled. Nothing changed."
A window left open for 10 minutes closes on its own. If it is slow, the card
adds a hint after a few minutes, but the window stays open; some 2-step checks
take a while.

You type your password only on Google's page. Find+ never sees it and has no
field for it. The window keeps nothing: it is a throwaway browser store, wiped
when the window closes, and it is separate from Safari, Chrome and every other
app.

This window is the main route in the app. In a normal browser tab (the
dashboard at http://127.0.0.1:8647 opened from Safari, say), the card cannot
open a window, so it uses the Chrome helper below instead.

### Unlock encrypted locations, in the same window

Google encrypts your Find Hub locations end to end. After you sign in, Find+
needs to unlock that encryption once before it can read any tracker. If it is
needed, the same window carries on to Google's unlock page and the card says
"One more step: enter your Android phone's screen lock in the same window."
Enter your phone's PIN, pattern or password there. That is what proves to
Google you are allowed the key. When the key is stored, the window closes and
the card shows **Connected as** your account with a **Locations unlocked**
chip. If you cancel at this step, you stay signed in and the card shows
**Locations locked** with an **Unlock encrypted locations** button to try again.

Find+ stores the key (`shared_key`) in `~/.findplus/secrets.json` at mode 0600
and never logs it. From a terminal, `findplus auth --unlock` does the same
with a Chrome window of its own.

If a poll ever reports that locations are locked again (for example after the
end-to-end data is reset on your account), the card and the menu bar ask you to
unlock once more.

### If the window is blocked

Google's policy is against sign-in inside apps, so it can refuse at any time:

> Find+ can sign you in to Google in a window of its own. Google's policy is
> against sign-in inside apps, so it can refuse at any time; if it does, sign
> in with your own Chrome instead.

If the window shows "This browser or app may not be secure", or Google says it
could not sign you in, Find+ notices, closes the window and says so on the
card: "Google would not let Find+ sign you in inside the app. Use your Chrome
instead." It remembers that for 7 days, and in that time the card leads with
your Chrome. You have two ways to go on, and neither needs the window.

**The Chrome helper.** The Find+ helper is a small open-source extension for
your own Chrome. Add it once:

1. On the card, open **More ways to sign in** and choose **Show the steps**
   under the helper. The card shows a folder path and a Copy button. Find+
   copies the helper into that folder (`~/.findplus/chrome-helper/<version>`)
   and opens nothing for you.
2. In Chrome, type `chrome://extensions` in the address bar and press Return.
3. Turn on **Developer mode** (top right), click **Load unpacked**, and choose
   the folder from step 1.
4. Come back to Find+ and click **Sign in with Google**. A tab opens in your
   Chrome, you sign in on Google's page, and a small "Signed in. You can close
   this tab." page appears. Find+ continues on its own, including the unlock
   step.

Why an extension: Google releases the Find Hub sign-in token and the
encryption keys only to a browser page, and Chrome no longer lets an outside
program drive your everyday profile. The helper, inside your own Chrome, passes
just those values to Find+ on 127.0.0.1. It talks to nothing else, has no
analytics and no remote code, and never sees your password. Its source is in
[`browser-helper/`](https://github.com/acamarata/findplus/tree/main/browser-helper),
and its privacy policy is
[here](https://github.com/acamarata/findplus/wiki/Chrome-helper-privacy).

**Pasting the cookie.** This needs no extension. Under **More ways to sign
in**, click **Sign in with your Chrome**. Find+ opens Google's own sign-in page,
`https://accounts.google.com/EmbeddedSetup`, as a normal tab of your Google
Chrome, and the card says where it opened it. Without Google Chrome, the page
opens in your default browser instead and the card says that; the steps below
are written for Chrome. Then:

1. Sign in to your Google account in that tab, including any 2-step prompt.
   The page may look blank or keep spinning after you sign in. That is
   expected.
2. Open Chrome's developer tools: Option+Command+I on a Mac, Ctrl+Shift+I on
   Windows or Linux.
3. Go to the Application tab, then Storage > Cookies >
   `https://accounts.google.com`.
4. Click the `oauth_token` row and copy its Value. It starts with `oauth2_4/`.
5. Paste it into the card with your Google email, then click **Connect**.

Find+ checks the token with Google, saves the session and shows "Connected
as" with your account. If Google refuses the token, the card says so in plain
words: "Google did not accept that token. It expires within minutes: sign in
again in Chrome and copy a fresh one." If Google cannot be reached, it says
that instead. The token expires within minutes, so copy it right after you
sign in. From a terminal, `findplus auth --token` does the same.

You can try the window again at any time with **Try the Find+ window again**.

### What Find+ stores, and what it never stores

| Stored | Where | Notes |
|---|---|---|
| Google session tokens and your account address | `~/.findplus/secrets.json` (0600, in a 0700 folder) | Never in the database, a backup, git or a log. |
| The encryption key (`shared_key`) | `~/.findplus/secrets.json` | Same file. |
| A note that Google blocked the window | `~/.findplus/native-signin.json` | A time and a reason, for 7 days. No token. |

Never stored: your Google password (you type it on Google's page), the
`oauth_token` cookie (exchanged with Google at once and dropped; never written
to disk, never logged), and anything the sign-in window held. The window's
cookies, history and cache are wiped when it closes, and Find+ does not copy
them anywhere. The logs name the host and path of a page the window was on, and
nothing after the path.

Find+ in its default setup never opens a separate Chrome window for sign-in.
Older versions (1.1 and earlier) did, with a profile at
`~/.findplus/chrome-profile`. That folder can still be on your disk; see
[Uninstall](Uninstall#older-versions-left-a-chrome-profile) to remove it.

### When a sign-in stops working

Google or Apple can end a sign-in on their side: a password change, a revoked
session, or an expiry. Find+ then cannot get new locations. It tells you once,
in three places:

- **Menu bar.** The icon dims and the top item of the menu changes to "Sign in
  to Google again...", "Unlock Google locations..." or "Sign in to Apple
  again...". Click it to go straight to that sign-in.
- **One banner.** A system notification reads "Find+ needs you". It appears
  once per loss, not on every poll, and only if you allowed notifications.
- **The dashboard.** A banner with one button, **Sign in again** (or **Unlock
  locations**), opens Settings and starts that sign-in.

Clicking any of them starts the same flow as the first time. When it finishes,
the banner and the menu item clear. Your trackers, places, groups and history
are kept throughout.

### Revoke Find+'s access from your Google account

Disconnecting in Find+ removes Find+'s own copy of your credentials. To also
end the session on Google's side, open your Google account's security page,
https://myaccount.google.com/security, and find **Your connections to third-party
apps and services** (or **Your devices**, depending on the account). Find the
Find+ sign-in, which usually appears as an Android device, and remove it. Find+
then shows the "sign in again" prompt described above. Changing your Google
password does the same.

### Troubleshooting

| What you see | What to do |
|---|---|
| The window never opens | Click **Connect** again. If the card says it could not open the window, use **Use your Chrome**. |
| "This browser or app may not be secure" | Google refused the window. Use the Chrome helper or the pasted cookie above. |
| A blank page after you sign in | Wait a few seconds. If the card still waits, close the window and click **Connect** again. |
| The window closed but the card says "Cancelled" | Command+W or Cancel was pressed. Start again. |
| "Locations locked" after signing in | Click **Unlock encrypted locations** and enter your Android screen lock in the window. |
| A banner keeps coming back | The sign-in is still lost. Click **Sign in again** and finish the window. |
| Nothing in the app reacts to the banner | Open **Settings**, then Sign-in, and click **Connect**. |

More in [Troubleshooting](Troubleshooting).

### Both ways

The buttons are Find+'s own, not Google's or Apple's sign-in buttons. Find+
does not use either company's sign-in service. The sign-in panel says so once,
under the cards: "Find+ is not affiliated with Apple or Google. Find Hub and
Find My are their trademarks."

A sign-in that fails or is cancelled part-way never shows as connected: the
card counts you as connected only once Find+ holds a Google session and the
account it belongs to.

What a Find Hub account gives you:

> This history consists of locations reported through Google's Find Hub
> network. Your trackers use nearby participating Android devices to report their
> location. Location updates can therefore be delayed, sparse, or
> unavailable, and this application should not be treated as real-time
> emergency or child-safety GPS tracking.

## Apple

Click **Connect** on the Apple card. A sheet opens asking for your Apple ID and
password. Find+ uses the password once and never stores it.

If Apple wants a second factor, the sheet turns into a code field, and it says
which kind of code to expect:

- **Trusted device.** Apple shows a 6-digit code on one of your iPhones, iPads
  or Macs. Enter it.
- **Text message.** If no trusted device is available, or you click **Use a text
  message instead**, Apple texts the code to your phone and the sheet says so.

Enter the code and the sheet checks it. A wrong code is named as such and the
field stays; **Start over** begins with a fresh form. **Cancel** (or Escape)
closes the sheet and nothing changes. When Apple accepts, the card says
**Connected as** your Apple ID. `findplus auth --provider apple-find-my` lists
every method Apple offers and lets you pick one.

Setting up both: connect Google and Apple one after the other, in either order.
The wizard's sign-in step shows the two cards side by side (stacked on a narrow
window) and lets you continue once one is connected. You can add the other
later in Settings.

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
accessories then report that sign-in is needed, and the menu bar, a banner and
the dashboard ask you to sign in again, as described under [When a sign-in
stops working](#when-a-sign-in-stops-working).

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

Once a card shows "Connected as ...", a **Disconnect** button appears next to
it, on both the dashboard's Settings > Sign-in and the setup wizard. Clicking
it opens an inline confirm row (never a native browser popup) that says what
disconnecting does and does not do, then a second click carries it out.

Disconnecting **Google** removes Find+'s own copy of your Google credentials
(`~/.findplus/secrets.json`): the AAS/ADM tokens, FCM credentials and the
end-to-end owner key. Your Google account itself is untouched; nothing is
revoked on Google's side; see [Revoke Find+'s access](#revoke-finds-access-from-your-google-account).

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

Sign-in tokens live only in `~/.findplus/secrets.json` and `apple-account.json`. They are never
copied into the daily database backups in `~/.findplus/backups/`, so a restore leaves
your sign-in as it is. See [Backup and restore](Backup-and-restore).

Every sign-in route is loopback-only, like the rest of the API, and sits behind
the app lock: while Find+ is locked, `/api/auth/*` returns `401` the same way
every other data route does. Starting a sign-in also requires the request to
carry an `Origin` or `Sec-Fetch-Site` header, which browsers and the macOS app
always send.

The in-app window talks to the daemon over seven routes under
`/api/auth/google/native/` (`begin`, `token`, `unlock`, `event`, `classify`,
`progress`, `cancel`). `begin`, `progress` and `cancel` need the same header
and sit behind the app lock; the four routes the window itself calls must come
from `http://127.0.0.1:<port>` with a Find+ client header and a live sign-in
started by `begin`, and are refused otherwise. See the
[API reference](API-reference).

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
terminal: it opens a Chrome window of its own for your Android screen lock and
stores the encryption key. `findplus auth --status` prints which providers you are signed in to, as
which account, and what is still missing; `--json` prints the same object the
dashboard reads from `GET /api/auth/status`. `--sign-out` removes that
provider's credential and exits; see [Sign out](#sign-out) above for exactly
what it does and does not remove.

Signing in is also step 2 of the [first-run wizard](First-run).

---
[[Home]]
