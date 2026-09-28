# Chrome Web Store listing: Find+ helper

Paste these fields into the Chrome Web Store developer console when creating the
listing. See `PUBLISHING.md` for the full step order.

## Name

Find+ helper

## Short description (<= 132 characters)

Connects your Google Find Hub account to Find+ running on your own computer. Talks only to Google and to Find+ on 127.0.0.1.

## Category

Productivity

## Full description

Find+ (https://github.com/acamarata/findplus) is a local, privacy-first app for
your Google Find Hub and Apple Find My trackers. It runs on your own computer.

Google hands the Find Hub sign-in token and the end-to-end encryption keys only
to a browser page, and Chrome no longer lets an outside program drive your
everyday profile. This helper, running inside your own Chrome, passes those two
values from Google's own pages to Find+ on 127.0.0.1 so that signing in feels
like any other "Sign in with Google" button.

What it does:

- On sign-in, it reads the oauth_token cookie that accounts.google.com sets
  after you sign in and hands it to Find+ on your machine, which exchanges it
  with Google right away and never stores it.
- On unlock, it relays the end-to-end vault keys that Google's unlock page
  produces after your Android screen-lock check, again only to Find+ on your
  machine.

What it does not do:

- It talks to no website other than accounts.google.com and 127.0.0.1.
- It contains no remote code, no analytics and no trackers.
- It never sees or stores your Google password, which you type on Google's own
  page.

The helper only listens while Find+, on the same computer, has started a sign-in
or unlock. It is open source; read every line at
https://github.com/acamarata/findplus/tree/main/browser-helper.

## Single-purpose statement

The single purpose of this extension is to connect a Google Find Hub account to
a Find+ installation running on the same computer, by passing the sign-in token
and the end-to-end encryption keys from Google's own pages to Find+ on
127.0.0.1.

## Permission justifications

- **cookies**: to read the single `oauth_token` cookie that
  `accounts.google.com` sets after sign-in, which is the Find Hub sign-in token,
  and only while a Find+ sign-in is in progress.
- **storage**: to remember, in session storage only, that a Find+ sign-in or
  unlock is in progress, so the extension knows when to listen.
- **host permission `https://accounts.google.com/*`**: to read that one cookie
  and to provide the vault-key hook on Google's own unlock page.
- **host permission `http://127.0.0.1/*`**: to pass the values to Find+ running
  locally, and to be told by Find+'s own begin page which flow is starting.

## Remote code

None. All code is contained in the package. The extension loads no remote
scripts and uses no eval.

## Data usage disclosures

- The extension handles **authentication information** (the Find Hub sign-in
  token and the account's end-to-end encryption keys).
- It transmits them only to the user's own Find+ installation on `127.0.0.1`,
  for the sole purpose of signing that Find+ install in to Find Hub.
- It is **not** sold or transferred to any third party.
- It is **not** used for any purpose unrelated to the single purpose above.
- It collects no browsing history, no analytics and no personal profile.

Privacy policy URL:
https://github.com/acamarata/findplus/wiki/Chrome-helper-privacy
