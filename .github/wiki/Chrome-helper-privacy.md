# Find+ helper privacy policy

This policy covers the "Find+ helper" Chrome extension, part of the open-source
Find+ project (https://github.com/acamarata/findplus). It is the privacy policy
referenced by the extension's Chrome Web Store listing.

In Find+ 1.2 the helper is a fallback: the Find+ app signs in to Google in its
own window first, and uses the helper only when Google refuses that window or
when you use the dashboard in a browser tab. You only need it in those cases.

## What the helper is for

The helper connects your Google Find Hub account to a Find+ installation running
on the same computer. Google releases the Find Hub sign-in token and the
account's end-to-end encryption keys only to a browser page, so the helper
passes those values from Google's own pages to Find+ on your machine.

## What it accesses

- The `oauth_token` cookie that `accounts.google.com` sets after you sign in.
  This is the Find Hub sign-in token. Chrome lets the helper see that this cookie
  changed at any time, but the helper acts on it only while a Find+ sign-in is
  in progress (started from Find+'s own page, expires after 10 minutes) and
  otherwise ignores it.
- The end-to-end vault keys that Google's unlock page produces after your
  Android screen-lock check. The helper forwards these only while a Find+ unlock is
  in progress (same 10-minute limit).

It never accesses your Google password, which you type on Google's own page.

## Where the data goes

The helper sends those values only to Find+ running on your own computer, at
`http://127.0.0.1:8647`, after checking that the program answering there is
Find+, together with a single-use token that Find+ generated for
that one sign-in or unlock. Find+ exchanges the sign-in token with Google right
away and does not store it.

The helper's Chrome permissions restrict it to two hosts: `accounts.google.com`
and `127.0.0.1:8647`. It cannot reach any other website.

## What it does not do

- It does not sell or transfer your data to anyone.
- It does not send anything to the Find+ authors or to any third-party server.
- It contains no analytics, no trackers and no remote code.
- It does not collect your browsing history or build any profile of you.

## Data retention

The helper keeps nothing of its own beyond a short session-storage note that a
sign-in or unlock is in progress. The note holds the single-use state, not a
token, expires after 10 minutes and is cleared by Chrome when the browser closes.
It stores no tokens or keys.

## Source

The extension is open source. You can read every line at
https://github.com/acamarata/findplus/tree/main/browser-helper .

## Contact

Questions or reports: open an issue at
https://github.com/acamarata/findplus/issues .
