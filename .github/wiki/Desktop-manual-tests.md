# Desktop manual test checklist

These five edge cases (PLAN.md § E13-T8) need a real signed or locally-built
`Find+.app` and a real macOS session. They are not exercised by `cargo
test` (which covers the pure `decide()`/`from_api()` branching instead).

- [ ] CLI daemon on port 8647 → tray shows a "CLI daemon v&lt;old&gt;" warning
      (run `findplus start --yes` from an older checkout, then launch
      Find+.app and confirm the log line, `daemon: CLI daemon v...`).
- [ ] Kill daemon process → tray icon dims within 90 s; "Restart daemon"
      appears (kill the sidecar's pid from `~/.findplus/daemon.json`, wait
      for the next 45 s poll plus the 20 s re-probe window).
- [ ] Lock via tray Lock item → tray icon dims; Poll Now disabled.
- [ ] Remove Chrome → sign out and back in → tray shows "Sign in" item
      instead of "Open Dashboard" (rename `/Applications/Google Chrome.app`
      temporarily, then `findplus auth`; check `GET /api/providers` reports
      `google-find-hub` unavailable with a Chrome-mentioning reason).
- [ ] Quit with sidecar running → confirm dialog appears with the exact
      wording "Polling stops when Find+ quits. Install the background
      service so it keeps running?" and all three buttons act correctly.
- [ ] No Dock icon and no Cmd-Tab entry at any point, including while the
      dashboard window is open (Activity Monitor still shows the process).
- [ ] Left-click the tray icon → the dashboard opens/focuses, no menu
      appears. Right-click → the menu appears instead.
- [ ] With the dashboard closed, reopen Find+.app from Applications or
      Spotlight → the dashboard opens and comes to the front, instead of
      nothing happening.

## In-app sign-in (1.2.0)

Owner-only: these need a real Google account, a real Apple ID and a real Find+.app, so no
test run covers them. Use a Mac you can sign in to Safari on, and run nothing else from Find+
while you test. Nothing here should open Finder, Chrome or a browser tab by itself. After each
step, write down "ok" or what you saw. Log lines below live in `~/.findplus/logs/`; each shows
only a host and a path, never a token, a cookie or a password. Send back lines that mention
`signin`, with the host and path only.

1. **Window loads.** Start with a fresh state (quit Find+, move `~/.findplus` aside), open
   Find+.app, and in the wizard click **Connect** on the Google card.
   Expect: a window titled "Find+ sign-in: Google (accounts.google.com)" with Google's page,
   and the card saying "Finish signing in in the Find+ window." Report: whether Google shows
   "This browser or app may not be secure" (yes or no) and the exact title.
2. **Sign in.** Enter your email, password and any 2-step prompt in the window.
   Expect: no "not secure" page; the page may look blank for a second after you sign in.
   Report: how long it took, and any extra page Google showed (passkey prompt, consent).
3. **Cookie captured, window closes.** Expect: the window closes by itself and the card shows
   "Connected as" your address. Report: yes or no, and whether the address was right.
4. **Unlock in the same window.** If the card says "One more step", enter your Android screen
   lock in the same window. Expect: it closes and the card shows "Locations unlocked".
   Report: whether the step appeared, and the card text at the end.
5. **What was stored.** In a terminal: `ls -l ~/.findplus/secrets.json` (expect `-rw-------`) and
   `/usr/bin/grep -c "oauth2_4/" ~/.findplus/logs/*` (expect 0 for every file). Report the two
   results. Do not send the secrets file.
6. **Nothing left behind.** Safari and Chrome are signed in exactly as before, and
   `ls ~/Library/WebKit/com.acamarata.findplus` shows no new Google data. Report: yes or no.
7. **Cmd+W cancels.** Disconnect Google in Settings, click **Connect**, then press Command+W in
   the window. Expect: the window closes and the card says "Cancelled. Nothing changed." Report:
   yes or no. Repeat, using the card's **Cancel** button: expect the window closes within about a
   second.
8. **Cancel during unlock.** Connect again; when the unlock step shows, press Command+W.
   Expect: the card shows "Connected as" with "Locations locked" and an **Unlock encrypted
   locations** button; clicking it opens the window again. Report: yes or no.
9. **Revoke, then the prompt.** At https://myaccount.google.com/security open the third-party
   connections (or devices) list and remove the Find+ sign-in. Wait up to two polls (about a
   minute). Expect all of these: the menu bar item "Sign in to Google again...", exactly one
   notification "Find+ needs you", and one dashboard banner with **Sign in again**. Report: which
   appeared, how many notifications, and how long it took.
10. **Deep links.** Run `open findplus://signin/google` in a terminal. Expect: the sign-in
    window opens while the prompt is active. Run it again after you sign in: Settings opens
    instead. Report: both results. Then click the menu bar item and the banner button and report
    that each opens the same window and that the banner and menu item clear once you finish.
11. **Apple, trusted device.** In Settings click **Connect** on the Apple card. Expect: a sheet
    for Apple ID and password, then a code field that says to use the code shown on your devices.
    Enter it. Expect: "Connected as" your Apple ID. Report: the wording of the code prompt.
12. **Apple, text message.** Disconnect Apple and start again, and at the code step click **Use
    a text message instead**. Expect: a message arrives and the prompt names your phone.
    Report: yes or no. Press Escape on a later attempt: the sheet closes and nothing changes.
13. **Both connected.** In a fresh wizard (or with both providers connected) the sign-in step
    shows two cards, both "Connected", and **Next** is enabled. Report: yes or no, and whether
    the cards sit side by side on a wide window.
14. **No Finder, no extensions page.** Throughout steps 1 to 13, nothing opened Finder, Chrome,
    `chrome://extensions` or a browser tab. Report: yes or no. Also open **More ways to sign
    in** and **Show the steps**: expect written steps and a copyable path, and nothing opens.
15. **If Google blocks the window.** If step 1 or 2 showed "not secure", note it. Expect: the card
    says "Google would not let Find+ sign you in inside the app. Use your Chrome instead." and
    offers **Use your Chrome** and **Show the steps**. Report: the card text, and whether the
    window closed itself.
16. **Read the log.** `/usr/bin/grep -i "signin" ~/.findplus/logs/* | tail -40`. Expect lines
    with a host and a path (for example `accounts.google.com /v3/signin/...`). Report any line
    saying "refused a navigation to host" with its host and path, and any line containing a
    value that looks like a token, which you should not send; tell the developer instead.
17. **A week later.** Sign in once more a week later and report whether Google flagged the
    account (a security email, a forced password change).
18. **Unlock with the right account, then the wrong one.** From the menu bar item "Unlock Google
    locations..." (after a key reset), sign in with the SAME Google account: expect "Locations
    unlocked". Repeat and sign in with a DIFFERENT Google account in the window: expect the card
    to refuse ("signed in to a different Google account" or "could not tell which Google account
    ... saved nothing") and nothing unlocked. Report both card texts.
19. **Try again while the window is open.** Click **Connect**, leave the window open, and click
    the card's button again (or the menu bar item). Expect: the same window comes to the front;
    no second window, and finishing the sign-in there still connects. Report: yes or no.
20. **Cancel while Google checks.** Click the card's **Cancel** right as the card says "Checking
    with Google..." (try a few times). Expect: within 5 seconds the card settles on "Connected
    as ..." (the sign-in had already gone through) or "Cancelled", never a spinner that stays.
    Report what it showed.
21. **One banner per loss, even after a restart.** With Google still revoked (step 9), quit
    Find+ and open it again twice. Expect: no new "Find+ needs you" notification on either
    start; the menu bar item is still there. Sign in again, revoke again: exactly one new
    notification. Report the counts.
22. **Frames and leaving Google.** In the log, `signin: refused a frame from host ...` lines are
    harmless (another site's frame inside Google's page). Report every
    `tried to leave Google for host ...` line with its host: each one ended the window.

## Automatic updates (1.2.1)

Run these on the installed app in `/Applications`. A dev run out of `target/` never installs
anything. Until a release newer than 1.2.1 exists, steps 3 to 6 use a folder of local builds.

1. **Settings > Updates.** Expect: "Installed: Find+ 1.2.1.", **Update Find+ automatically**
   ticked, and the sentence about GitHub's releases API. Click **Check now**. Expect "Checking..."
   then "This is the newest version." and a fresh "Last checked" time. Report the line.
2. **Off means quiet.** Untick the switch, wait a day, run `findplus update status`. Expect
   "automatic off" and the same "last check" time as before. Tick it again. Report yes or no.
3. **A local build.** Build and sign the app the usual way (`packaging/scripts/release-local.sh`),
   then `findplus update dev-dir <the folder holding Find+.app>`. Close every Find+ window and
   wait about 8 minutes. Expect: Find+ quits and comes back by itself, `findplus update status`
   shows nothing staged, `findplus db backups` lists a new "preupdate" backup, and
   `~/.findplus/updates/update.log` ends with "installed Find+ ...". Report the last 5 log lines.
4. **Restart to update.** Rebuild, open the dashboard and keep it focused. Expect within a few
   minutes: the menu bar menu shows **Restart to update (v1.2.1)** and the dashboard shows the
   corner button. Click either. Expect: Find+ restarts on the new build within a minute, and your
   map, places and history are all there. Report yes or no.
5. **A refused build.** Put an unsigned or ad-hoc signed build in the folder (a plain
   `cargo tauri build` without your signing identity). Expect: Find+ does not restart; Settings >
   Updates says the last install did not finish; the app you had keeps running. Report the text.
6. **Back to releases.** `findplus update dev-dir --clear`. When 1.2.2 is published, leave Find+
   idle and expect the same quiet restart onto 1.2.2. Report the version Settings shows after.
