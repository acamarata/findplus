# Changelog

All notable changes to Find+ are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.1.6] - Unreleased

### Added
- Sightings that look wrong are caught and left out of stays, trips and alerts: a tracker that
  jumps 2.5 km and straight back, an impossible speed, a stray at the edge of a day, or one tracker
  disagreeing with the rest of its person. Raw history is never changed. Scores live in a derived
  table, with `findplus db recompute-quality [--since DATE]`. `GET /api/latest`, the timeline and
  every export carry `suspect` and `suspect_reason`; `/api/trips` lists these under `outliers` with
  `reasons`. A lone far sighting is held from place alerts for one poll (12 minutes at most),
  and the alert keeps the sighting's own time. Spikes are caught at Find Hub's real 2 to 10
  minute cadence, not only one minute apart.
- Database backups: a verified online copy once a day (and at startup when the newest is a day
  old), kept 7 daily and 4 weekly in `~/.findplus/backups` (0700, files 0600, no sign-in tokens or keys;
  the app-lock PIN hash is in the copy).
  `findplus db backup`, `db backups`, `db check`, and a safe `db restore <file>` (checks the file,
  refuses while running, takes a pre-restore backup, keeps the replaced file). Backup folder and
  counts are settings (`backup.directory`, `backup.keep_daily`, `backup.keep_weekly`).
- `findplus doctor` checks database integrity and backups. A damaged database at startup makes the
  daemon read-only with a restore banner; the file is never deleted.
- `findplus export --format jsonl` and `findplus import FILE`: a full-fidelity, human-readable
  export of devices, observations, places, groups (with kinds and members) and alert rules.
- People and pets. Find+ suggests people from tracker names ("Sam Bag", "Sam Bike", "Sam Shoes
  Red" become Sam), always as a preview you accept, edit or dismiss; one-word names ask "person or
  pet?" and nameless trackers ask "Whose is this?". `GET /api/people/suggestions`,
  `findplus people suggest|accept|list|set-role`, and MCP tools to match.
- Where a person probably is, from the trackers that are actually carried, in plain words: likely,
  probably, not sure, or no recent sightings (`GET /api/people/{id}/now`). A tracker counts as
  carried for 45 minutes after it last moved. Trackers that never moved cannot move a person: when
  the carried one goes quiet, the person stays where they were and it reads "no recent sighting".
- One alert per person crossing, naming the tracker that saw it: "Sam just arrived at Grandma's"
  only when the sighting is under 10 minutes old, otherwise the time.
- Left-behind trackers: "Sam's bag looks left at School", once per episode (even when the bag goes
  quiet and reports again), never at Home, only on rules for any place or that place.
- Every new place gets an arrive and leave rule for everyone on your connected channel;
  `POST /api/places/notify-defaults` adds it to existing places, with a dry run first.
- Places have a kind (home, school, work, family, shop, other), guessed from the name. Places you
  already have get the guess on upgrade, shown in the Places list with a one-tap confirm.
- One message per person crossing even when several rules match it. A person's rule replaces a
  tracker's own alert only when the person really had that crossing. Pets are off by default on
  the everyone rules; a rule naming the pet still alerts.
- A Person page (`#/person/<id>?date=YYYY-MM-DD`): click a person's name on a group card, in an
  alert rule sentence, the delivery log or the arrivals list. It shows where they probably are now,
  a day bar (arrows, date picker, Today, left and right keys), the day summary with each line
  focusing the map and the day story, one map line and one lane per tracker (best sighting first),
  each tracker's role, weight and chip (carried, left at School, moved without Sam, no recent
  sighting), Send today's summary, Notify me, Edit person and Full map. Loading, empty day,
  partial, error with Retry, offline and locked are all handled; a lock leaves no name or place.
- "We found people in your trackers": a panel on the Groups tab, a dashboard banner and the wizard's
  Groups step offer each guess as a card (Accept, Edit members, Not a person, It's a pet), ask
  "person or pet?" and "Whose is this?", and have Accept all and Check again. Nothing is applied
  without a click.
- The place dialog has a kind (guessed, with a Home hint), a "Tell me when anyone arrives or leaves"
  box (on by default; the channel is picked for you when one is connected, a select when several,
  off with a reason when none), and no second dialog after Save. Places saved earlier get a
  "Notify me" banner that previews before it writes. `POST /api/places` takes `notify_channels`;
  `GET /api/alerts/rules` carries `all_people`.
- Sightings that look wrong are drawn faintly in a dashed ring with the reason on hover, behind a
  "Show sightings that look wrong" box (on by default), and add nothing to a day's distance.
- The dashboard says "Sam's bag looks left at School since 3:00 PM", admits it is a guess, and has
  "I know". Settings gains the daily summary (on/off, time, channel, per person, Send now), the
  left-behind switch, and a backup line with Back up now (`GET /api/settings/backup`,
  `POST /api/settings/backup/now`).
- A daily summary for each person ("Sam's day"): when they left Home, arrived at School, left
  again and got home, stops of 15 minutes or more away from saved places, long gaps with no
  sightings, trackers left behind, and where they are now. Every line names the tracker that backs
  it, a time reads "around" when the sightings that bound it are over 10 minutes apart, and "still
  at" is only said on fresh data. `GET /api/people/{id}/day`, `findplus day <name>`, and the MCP
  tools `get_person_day` and `where_is`.
- Send it to Telegram: `POST /api/people/{id}/day/send`, `findplus day <name> --send`, or an
  evening summary (setting `people.digest`, off by default, 20:00, `findplus people digest`). Each
  person's day goes once per chat per day, never twice after a restart, and is held while the app
  lock is on. A day with nothing tracked sends nothing unless you choose "always send".
- Adding a place now ends with "who should be told, and where": the alert-rule dialog opens with the
  new place chosen. A place with no rule says "Not notifying anyone yet" in the Places list, with a
  Set up an alert button.
- The rule dialog writes the rule in plain words ("Tell me on Telegram when Sam Bag leaves
  School."), lists what Save still needs, explains how a group decides, says why a channel is greyed
  out, can send a real test message to the ticked channels, and shows what the rule would have sent
  in the last 24 hours (`POST /api/alerts/rules/dry-run`, read-only).
- Webhook has its own Send a test message now button. The Alerts tab opens with a strip of
  connected channels and the rule count, Telegram setup lists its four steps, and the delivery log
  has status and channel filters and pages 15 rows at a time.
- Places: search and sort, coordinates and rule count on each card, a rule-count line when editing,
  relative times in Recent arrivals and departures, and a note under the radius that very small
  places can report late.

### Changed
- The database now syncs every commit to disk (`synchronous=FULL`, WAL kept) so a power cut cannot
  lose the last sightings.
- A tracker belongs to at most one person; adding it to a second one is refused with 409.
- `findplus export --format jsonl` now also carries your settings (not the app lock), alert
  deliveries and digest runs, so cooldowns and daily summaries do not repeat after an import. The
  new `findplus db rebuild-derived` replays every sighting into place, group and person state and
  marks the rebuilt events as already sent. `findplus import` and `findplus db import` are the same
  command; the docs use `findplus import`.
- A chosen backup folder gets a `findplus-backups` folder inside it; only that folder is made
  private. Manual and pre-restore backups keep the newest 10 and 5.
- The geofence is accuracy-aware. A fix whose accuracy circle straddles the edge of a place is
  uncertain and neither enters nor exits. Leaving needs a fix beyond the radius plus the larger of
  its accuracy and half the radius (at least 50 m), confirmed as many times as the place asks. Find+
  recommends a radius of at least 100 m.
- The people engine ingest hook no longer scans every sighting, so a large database stays quick.
- A person enters a place only when their own trusted sighting is inside it.
- The wizard's Places step shows each place's kind and alert state. The Person page has better
  contrast, a phone layout, arrow keys on the story rows and a map named for the person.
- Telegram messages now carry people's names, place names and times, and the daily summary does too.
  The app lock does not stop alerts or summaries going out. See the Privacy page.

### Fixed
- `findplus db restore` now works over a damaged database (the case it exists for): the damaged
  file is kept whole as `.replaced-<time>` with its `-wal` and `-shm`, and a failed backup prints
  plain words instead of a traceback. Restore also refuses a file with a missing table, keeps every
  replaced file even when two restores share a second, stops if the old log cannot be folded in,
  and `serve` holds a lock file so a starting or wedged daemon is noticed too.
- A config value with a line break, `=` or null can no longer add other keys to `config.env` (it
  could slip past the 7-day retention and 5-minute poll rules). Hand-edited bad values are ignored.
- CLI write commands (`poll-now`, `prune`, `db recompute-quality`, `import`, `db rebuild-derived`)
  check the database first and refuse on a damaged file; the other commands only read it.
- `findplus db recompute-quality` commits in chunks, so it no longer locks out the poller.
- `~` in `backup.directory` is expanded; a stray file name or dangling link in the backup folder no
  longer breaks listing, scheduled backups, Settings or `doctor`; a backup stamped in the future no
  longer stops automatic backups. A repeated sighting in an import file gives a plain message.
- "Poll now" is refused with a clear message while the database is read-only.
- Repeating a lock call keeps the lock screen's error, and the forgot-PIN help also shows after a
  lockout.
- A tracker that keeps reporting the same place is no longer marked suspect or left behind.
- A person's carried state settles 45 minutes after the last move, a single stray fix no longer
  skips the two-exit confirmation, and a fast-clock reporter cannot freeze a person's state.
- A held fix is released on every poll cycle, not only after an ingest, and a tracker that
  disagrees with its siblings is held too. Cleared fixes reach the geofence and rescore their
  siblings.
- Left-behind alerts confirm on the person's own sightings and respect a rule's place.
- Map tooltips show tracker, place and reason text as plain text, never as markup. The content
  security policy forbids form posts, base tags and plugins. MCP tools quote path segments, and
  `add_place` through MCP takes a `notify` flag. The daily summary sends while Find+ is locked,
  like alerts, and a lock forgets hidden people suggestions.

## [1.1.5] - 2026-10-01

### Added
- Google sign-in now leads with a single **Sign in with Google** button. Find+ opens Google's
  sign-in in the Chrome you already use, and the new open-source **Find+ helper for Chrome**
  extension (`browser-helper/`) passes the sign-in token and the end-to-end unlock keys to Find+
  on 127.0.0.1. You land on a "Signed in. You can close this tab." page and the card advances on
  its own. The helper talks only to Google and to 127.0.0.1, with no analytics and no remote
  code. A one-time "Add the helper to Chrome" step (Show helper folder, Open Chrome extensions,
  Load unpacked) is built into the card, and the helper ships inside the app. The older paste
  flow and the separate-window flow move under "Other ways to sign in". New endpoints:
  `POST /api/auth/google/helper/{begin,unlock-begin,token,unlock,seen,reveal,open-extensions}`.
  The two ingest routes accept only the pinned extension origin and a single-use state.
- Groundwork to publish the helper on the Chrome Web Store: a keyless store-zip build
  (`packaging/scripts/build-chrome-helper.sh`), a listing kit and privacy policy, and a
  generated icon and promo tile.
- `update-app.sh` (a release asset): update the macOS app while it is running. It quits Find+ and its
  daemon, verifies the dmg checksum, swaps the app and starts it again; your data is untouched.
  The checksum catches a corrupted download. It does not prove who published the release.
- The dashboard has an **Unlock** action, and its status refreshes by itself and polls at once
  after you act.
- When the Chrome helper is detected, **Unlock encrypted locations** and `findplus auth` use it
  too; the separate Find+ Chrome window stays as the other way.
- The groups page explains why a group is empty or locked, and lists devices that are not
  tracked.
- `install.sh --help` prints usage. The Homebrew caveats, README and Install page now mention the
  one-time Chrome helper step for every install route.
- The macOS app bundle now ships a notices file with the licences of the packages inside it.
  Leaflet's licence text sits next to its vendored copy.

### Changed
- Group names are trimmed and compared without regard to case, so "Family" and "family" no longer
  both exist.
- JSON, KML and CSV exports label distances as approximate.
- `update-app.sh` restarts the login-service daemon after it swaps the app.
- The helper sign-in leads in the README and wiki; the paste route is marked as the fallback.
- Release builds on a tag now fail rather than ship an unsigned app. Only the signed Apple Silicon
  dmg is attached to a release. CI runs with read-only token permissions by default and scans for
  secrets with gitleaks.

- The Chrome helper only talks to Find+ on port 8647 (checked against `/api/health`), forgets a
  pending sign-in after 10 minutes, and only moves the tab that started the flow.
- Devices that share a name get a short id suffix in pickers, group notes, place events and
  export file names.

### Fixed
- Groups saved by older versions with case-variant or very long names can be edited again, and a
  member that is no longer tracked can be removed from a group.
- Poll Now while signed out ends in seconds and says why. Trackers Find Hub has no newer sighting
  for are listed as "no recent sighting", not as errors, and the banner no longer claims they
  "reported the same place".
- A failed helper hand-off shows its reason on the card and can be retried; "Switch Google
  account" waits for the new sign-in instead of finishing on the old one.
- Disconnect cancels a running sign-in or unlock, so a late job cannot sign you back in.
- The timeline and Groups panes show an error with a Retry button instead of stale or blank
  content, and timeline entries work from the keyboard.
- `update-app.sh` checks the new app's signature and architecture, and rolls back if the swap
  fails.
- The unlock wait loop can be cancelled, times out, and ends cleanly.
- The helper's token and unlock hand-off, and its "seen" ping, work while the app lock is on.
- The unlock key is tagged with its Google account, and a key that belongs to another account is
  refused.
- Disconnect also empties the Google data held in the Find+ Chrome profile.
- A revoked Google login now reads as signed out and offers a sign-in prompt.
- A location report Find+ cannot decrypt counts as a failed poll, not as "no data".
- Find+ no longer backs off when no Google traffic happened.
- After you unlock encrypted locations or sign in, Find+ now polls straight away and clears its
  retry delay. Before, the dashboard stayed empty for up to ten minutes after a successful unlock.
- The dashboard map no longer renders into a small corner box when the window or layout changes
  size after start-up; it re-measures whenever its area resizes.

## [1.1.4] - 2026-09-27

### Added
- Google sign-in now starts with **Sign in with your Chrome**: Find+ opens Google's sign-in page
  as a normal tab of the Chrome you already use, shows five short steps for copying the
  `oauth_token` cookie from Chrome's developer tools, and signs in once you paste it with your
  email. Chrome 136 and later refuse automation of your everyday profile, and Google hands this
  token only to a browser, so the copy step is the way to use your own Chrome. Find+ exchanges
  the token right away and never stores, logs or echoes it. The older flow stays as a smaller
  option, "Or let Find+ open its own Chrome window". New routes: `POST /api/auth/google/open` and
  `POST /api/auth/google/token`. From a terminal: `findplus auth --token` (or set
  `FINDPLUS_OAUTH_TOKEN`).
- **Unlock encrypted locations**: Google encrypts Find Hub locations end to end, so after signing
  in the card shows an unlock step. It opens a Chrome window of Find+'s own where Google asks for
  your Android phone's screen lock, once; Find+ stores the key and never asks you to paste code.
  A locked account now shows this step (and a poll reports it) instead of failing to decrypt. New
  routes: `POST /api/auth/google/unlock/{start,cancel}` and `GET /api/auth/google/unlock/progress`.
  From a terminal: `findplus auth --unlock`.

### Changed
- Find+ is now menu-bar only on macOS: no Dock icon, ever. The tray icon is a simple "F+" glyph
  that dims when the daemon is down or starting, nothing is signed in, data is stale, or there
  is an error, and shows at full opacity when everything is healthy. Click the tray icon to
  open the dashboard (devices, groups, timeline); right-click for the menu. Reopening Find+
  from Applications or Spotlight while it is already running now brings the dashboard forward
  instead of doing nothing.

### Fixed
- A Google sign-in that failed or was cancelled part-way no longer shows as signed in with no
  account. Signed in now means Find+ holds a Google session and the account it belongs to, in the
  dashboard, `findplus auth --status`, `findplus doctor` and `findplus start`.
- Signing in to a different Google account drops the previous account's encryption keys, so the
  first poll fetches the new account's keys instead of failing to decrypt.

### Security
- The vendored Google code's key-retrieval path could open a browser and run `pkill -f chrome`
  (closing your own Chrome) on its own during a poll. Find+ now neutralizes that path: a poll of
  a locked account raises a typed "needs unlock" state instead of launching a browser or blocking,
  and a real browser is opened only for a sign-in or unlock you start yourself.

## [1.1.3] - 2026-09-26

### Added
- Alert rules can now pick a subset of your saved Telegram chats instead of always messaging
  all of them: a "Telegram chats" picker on the rule dialog defaults to "All chats" (every
  existing rule keeps behaving exactly as before) and can be narrowed to one or a few. The
  CLI's equivalent is `findplus alerts rules add/edit --telegram-target <id>` (repeatable) and
  `--telegram-all`.
- Sign-in cards for both Google and Apple now have a Disconnect button, so you can remove a
  stored account without losing the trackers or history it already collected. The CLI has the
  same option: `findplus auth --sign-out --provider google` (or `apple`).
- A Cancel button appears while Google sign-in is waiting on Chrome, so you can back out of a
  stuck sign-in instead of force-quitting the app.
- Pick on map: set a place by clicking the map instead of typing coordinates. Drag the pin or
  nudge it with the arrow keys, resize the geofence with a handle on its circle or the radius
  box, and the dialog shows the coordinates you picked before you save.
- A "Recent arrivals and departures" panel on the Places tab lists each device's or group's
  last few entries and exits.
- Telegram targets show as chips with the chat's or person's name. Typing an @username looks it
  up and saves it as a chat ID. A person has to send your bot any message first, because
  Telegram does not let bots message people who have not; Find+ tells you when that is the
  problem. "Find chat IDs" marks chats you have already added.
- `findplus alerts rules edit` brings the CLI in line with the dashboard: change a rule's name,
  place, on-enter/on-exit, channels, cooldown or enabled state without deleting and recreating
  it.

### Changed
- Every remaining native confirm, prompt and alert popup is now an in-app dialog that matches
  the rest of Find+, including the delete confirmations for places, groups and alert rules and
  the history-deletion prompts.
- The default theme now follows your system's light/dark setting instead of always starting
  in dark mode.
- Deleting a place or group that still has alert rules attached now says so in the confirmation,
  and how many rules go with it.
- Dialog titles, Cancel buttons and controls for a channel you have not connected yet got a
  consistent style pass across Settings, sign-in and Alerts: a title now reads as the actual
  question instead of repeating the button below it, and a disabled control now looks and acts
  disabled instead of only failing once clicked.
- Every sign-in card area now says Find+ is not affiliated with Google or Apple.
- A new install with no account connected shows one clear "Connect an account" action, the
  status dot turns amber when polls fail instead of staying green, and poll problems read as
  plain sentences with a button that fixes them instead of raw error codes.
- The dashboard, dialogs and setup wizard fit a phone screen without sideways scrolling, text
  fields are styled in dark mode, and the Settings units sit next to their fields.
- Delivery-log errors, chat labels and timestamps read in plain, consistent language instead of
  raw server text or mismatched time formats.

### Fixed
- Google sign-in no longer fails with "chrome not reachable" on a Mac that also has Chromium
  installed (for example from Homebrew). Find+ now always opens Google Chrome itself.
- A device refresh that failed partway through setup no longer wipes your already-tracked
  device list; if the refresh fails, your existing choices are kept.
- Saving alert settings without changing the webhook URL no longer overwrites it with the
  masked placeholder shown on screen, which used to silently break the webhook.
- A newly created place now asks for one confirmed arrival before it counts as "arrived",
  not two.
- The lock screen no longer lets a still-loading dashboard reappear behind it.
- Dashboard controls (Settings, the tabs, and the rest of the top bar) are wired up before the
  page finishes loading, so an early click during a slow load is never silently dropped.
- A group's presence tooltip could describe a headline the pill itself no longer showed; layout
  and heading alignment are also cleaned up across the Places, Groups and Alerts side panels.

## [1.1.2] - 2026-09-25

### Fixed
- Google sign-in now opens Chrome from the macOS app. In 1.1.1 the app's bundled daemon crashed as it started the Chrome helper, so clicking the button did nothing visible.
- The first Google sign-in on a new install no longer aborts before Chrome opens. Find+ created its private token file empty, and the sign-in code could not read an empty file. An empty file left by that bug is repaired.
- Apple Find My sign-in, two-factor codes and location polling now use the findmy library's real 0.10 interface. Earlier builds called functions that library does not have, so Apple sign-in could not complete, and the macOS app did not include the library at all.
- Find+ no longer stores your Apple ID password. The saved Apple session keeps only Apple's tokens, and when they expire Find+ asks you to sign in again.
- Accessory keys exported from Find My as pairing plists load correctly, and keys of the wrong length are refused at upload instead of never decrypting.

### Added
- Telegram alerts go to one or more targets, separated by commas: your own user ID, a group or supergroup ID, or an @username (up to 10). Each target is delivered and retried on its own, so one failing target never blocks or repeats the others, and the delivery log and Send test show the result per target.
- "Find chat IDs" lists the chats your bot has seen (after you message it, or add it to a group and post there), so you can add a target without looking up IDs by hand.
- `findplus selfcheck` confirms an install can start the Google sign-in helper and has its Google and Apple libraries.

### Changed
- The setup wizard's sign-in step and Settings > Sign-in now share one set of provider cards, with buttons that say what they do: "Connect Google Find Hub" and "Connect Apple Find My". Each card shows what is happening (opening Chrome, waiting for you in the Chrome window, saving the session, checking a code) and, when a sign-in cannot start or does not finish, the reason in plain words with a Try again button. A click that used to do nothing visible now always says something.
- An install without the Apple extra shows how to add it instead of an Apple ID form that could only fail.
- The setup wizard has a clearer step header and progress bar, larger step titles, and Back, Skip and Next laid out as secondary, quiet and primary actions, in both themes and at phone width.

## [1.1.1] - 2026-09-25

### Fixed
- The macOS app no longer quits a few seconds after launch once setup is finished. 1.1.0 closed its splash window, had no other window open, and exited, so the menu bar icon disappeared while the background daemon kept running. Closing the dashboard window no longer quits the app either; use Quit in the menu bar menu.
- The Homebrew formula names its Python resources the way `brew audit` expects, and the release workflow hashes the source package attached to the release rather than a fresh CI build.
- Startup no longer wipes an error shown in an open Settings dialog (the poll interval's field error could flip back to hidden if you opened Settings while the dashboard was still loading).

### Changed
- Install instructions no longer mention `pipx install findplus`: Find+ is not on PyPI. Install from the release wheel, Homebrew or the curl installer.

## [1.1.0] - 2026-09-21

### Added
- `alerts deliveries --json` prints the delivery log as JSON, matching `alerts rules list --json`.
- The place dialog can now fill its coordinates two ways instead of only a map click: "Use a tracker's last location" picks any tracked device's most recent fix, and an opt-in address search (type an address, press Search) queries OpenStreetMap's Nominatim through the daemon, never the browser, only when you press the button.
- The Places tab's side panel lists every saved place, with its color, radius and who is currently inside it, plus Edit, Delete and click-to-centre on each row.
- Devices and groups can now use a custom uploaded PNG as their badge icon, alongside the bundled Lucide glyphs and letter badges. Upload one from the icon picker's "Your icons" section; an icon still in use cannot be deleted. The macOS widget cannot fetch images, so a custom icon shows there as a letter badge instead.
- A second macOS widget, "Find+ Places": who is at each saved place right now, with a device or group badge per occupant and the last time it changed. Tapping it opens the dashboard's Places tab.
- A failed Telegram, WhatsApp or webhook alert now retries automatically when the failure looks temporary (a timeout, a "too many requests" response, or a server error): up to three more tries, one minute, five minutes, then thirty minutes after the first failure. A rejected request, a bad credential or an unconfigured channel is not retried. The delivery log shows a retry in progress and how many tries a delivery has used.
- The release workflow can build an Intel (x86_64) app on its own runner. No Intel dmg was published: the app ships for Apple Silicon only, and Intel Macs use Homebrew or the curl installer with the dashboard in a browser.
- The macOS app opens the dashboard by itself on a first launch, so the setup wizard is the first thing you see, and goes back to being tray-only once setup is finished. The splash window now closes when the daemon is up, instead of staying on top until you quit.
- Settings now carries the poll interval, how long history is kept, whether Mac notifications may name the person and place, and a Run setup again button.
- A fresh install opens the setup wizard by itself. If you go somewhere else first, a bar under the toolbar offers to resume it, and stays until setup is actually finished.
- The wizard's last four steps: saved places, alert channels, the app lock, and a summary. Every channel shows what it does with your alert text before you can switch it on.
- The wizard's first four steps: what Find+ is, signing in to Google or Apple, choosing which trackers to poll, and putting them in a group. Every step can be skipped and none of them is a dead end.
- A sign-in panel at the top of the Settings dialog, for Google Find Hub and Apple Find My. The Google card follows the Chrome sign-in as it runs and offers a download link when Chrome is missing; the Apple card asks for the two-factor code when Apple wants one.
- An onboarding wizard for the dashboard. The daemon remembers which step you reached in `onboarding.last_step` and whether you finished in `onboarding.completed_at`, both readable on `GET /api/settings` and writable per key, so closing the tab halfway resumes where you left off.
- Sign in to Google Find Hub from the dashboard: `POST /api/auth/google/start` opens Chrome and `GET /api/auth/google/progress` reports how far along it is. Chrome now runs in a profile of its own under `~/.findplus/chrome-profile`, so signing in no longer closes the Chrome windows you already have open.
- Sign in to Apple Find My from the dashboard, 2FA included: `POST /api/auth/apple/start` then `POST /api/auth/apple/code`. Your Apple password is used for the sign-in call and is never stored, logged or sent back.
- `GET /api/auth/status` reports, per provider, whether you are signed in, which account, and what is still missing (Chrome, or the Apple extra).
- `findplus auth --status` prints that same report as a table, or as JSON with `--json`.
- Register an Apple Find My accessory from the dashboard's Apple card, by choosing a key file (a `.plist` export or a `.json` holding the base64 private key): `POST /api/apple/accessories`. A tag you have already registered asks before it is replaced, rather than quietly replacing or silently refusing it.
- `findplus doctor` now checks the Chrome profile directory is owner-only, and repairs it with `--repair`.
- `findplus setup`, a guided first-run walkthrough in the terminal for installs that never open the dashboard. Pass `--yes` to accept every default without a prompt.
- The daemon prunes location history, place visits and group events older than the retention window once a day, with no restart needed after changing it.
- `install.sh --start` installs, runs the setup wizard and starts the service in one command. A fresh install finishes by asking you to sign in, which is a success, not an error.
- The Alerts tab has a Delivery log showing each alert's rule, channel, kind, message text and body, time, status and error.
- An Uninstall page in the wiki with the manual service-removal commands for macOS, Linux and Windows.
- A bundled Lucide icon sprite (48 icons, ISC licensed) the dashboard loads once at startup.
- An icon picker for device and group badges: the 48 bundled icons grouped by kind, a letter of your choice, or a plain colored dot.
- A color picker for device and group badges: the 12 palette colors, or any color you pick.
- One badge renderer behind the map markers, the timeline track heads and the group legend, so a device's icon and color look the same everywhere.
- An i18n scaffold for the dashboard: `web/app/i18n.js` and the English catalog at `web/locales/en.json`, whose honesty sentences are generated from the same source the API serves. Every string the dashboard shows now comes from that catalog, so a second language can replace one file.
- A phone-width layout: under 600px the dashboard gets a bottom tab bar, the toolbar collapses behind a More button, dialogs open full screen, and every button and tick box is at least 44px to tap.
- WCAG 2.1 AA groundwork: page landmarks, a label on every form control, a visible focus ring, a focus trap and Escape-to-close on the Devices and Settings dialogs, an announced alert banner, and color changes where text or a control border fell short of the contrast minimum.
- An accessibility scan in the browser test suite: axe-core over every tab, in both themes, at desktop and phone width.
- An alert rule can now pick any combination of Telegram, webhook, WhatsApp and Mac notifications, through a checkbox set in the rule form and a repeatable `--channel` option on `findplus alerts rules add`. Mac notifications only appear as a choice on macOS.
- Native macOS notifications for alerts. The daemon queues them and the menu bar app shows them, so an alert arrives even with no dashboard window open. While Find+ is locked, or unless you turn notification details on, the banner says only "Find+ alert", because a notification preview can appear on a locked screen.
- WhatsApp alerts, relayed through CallMeBot. The setup text says plainly that your alert text passes through a third party before it reaches WhatsApp. Set it up in the Alerts tab, which carries that text and the CallMeBot contact details, or from the terminal with `findplus alerts whatsapp set`/`clear`; the routes behind it are `PUT`/`DELETE /api/alerts/channels/whatsapp`. The phone number is shown masked and the API key is never returned.
- Alert rules can target more than one channel at once. Each channel gets its own delivery row and its own cooldown, so a notification on one never suppresses another.
- Device and group labels, icons and colors: `PATCH /api/devices/{id}`, `GET /api/icons`, `findplus devices label`/`findplus devices icons`, exports and the macOS widget all carry the new fields. A label is local only and survives every provider name refresh.
- Edit a device's label, icon and color from the dashboard: every row in the Devices dialog has an Edit button, and the choice shows up on the device list, on every map marker, on the timeline track heads and in the macOS widget.
- A group create and edit dialog on the Groups tab: name, icon, color, quorum, cluster radius, stale-after minutes and which tracked devices belong to the group.
- Group cards on the Groups tab, each with the group badge, its member avatars, its live presence verdict, and edit and delete buttons.

### Changed
- `findplus devices`' request-rate hint names "requests" generically instead of always saying "Google requests/hour", so it reads right for an Apple-only setup.
- Alert rule cards and `alerts rules list` show channel names like "Desktop notification" and "WhatsApp" instead of raw ids such as `native`/`whatsapp`.
- CLI and dialog device counts use the right singular or plural ("1 device tracked" vs "6 devices tracked") instead of always "device(s)".
- CI runs the accessibility scan, the icon and catalog drift check, and the Rust notification tests as three lanes of their own, so each failure names itself.
- README and wiki screenshots are regenerated at 1280x800, with a matching phone-width set at 375x812.
- The Chrome-not-found message is one sentence now shared by the terminal, the API and `/api/config`, instead of two wordings that could drift apart.
- Starting a sign-in requires the request to carry an `Origin` or `Sec-Fetch-Site` header. Browsers and the desktop app always send one; nothing else has a reason to start a sign-in.
- `PUT /api/settings` is now `PATCH /api/settings`, and its body carries the poll interval, the history retention period and whether native notifications may show details.
- The Homebrew caveats and the installer both point new installs at `findplus setup`, so every install channel gives the same first instruction.
- `findplus start` finishes a fresh sign-in in one run: it discovers devices from every provider you are signed in to, shows them, tracks them all and installs the service. Pass `--no-track-all` to discover without tracking.
- `findplus start` exits 4 when you are not signed in yet, instead of 0, and counts an Apple sign-in as being signed in.
- `install.sh` is shorter and points at a new Uninstall wiki page for the manual service-removal commands it prints. Without `--start` its last line now points at `findplus setup`.
- `findplus start` asks "Install and start the service now? [Y/n]" in an interactive terminal instead of only printing "Pass --yes"; a script or pipe with no terminal still needs `--yes`.
- `findplus devices` lists from the local database by default instead of always re-querying Find Hub, so it works without a signed-in account; `--refresh` opts back into the live query. It also gained a Label column, and `--json` carries the field.
- `findplus alerts rules list` and `findplus devices` render their tables with the same aligned-column helper, fixing a jammed header and missing columns in the alerts table.
- A wrong PIN on the lock screen now shows the server's real "Incorrect PIN" message with a pointer to `findplus lock reset`, instead of the generic word "Locked".
- `findplus lock reset` is a new, easier-to-find name for the existing PIN-recovery command, alongside `findplus reset-lock` and `findplus pin reset`.

### Fixed
- The place dialog is now styled like the device and group editors, instead of painting as an unstyled browser-default strip across the map, and "Add place" opens it directly at the map's current centre -- no map click required, so it is fully keyboard-reachable.
- The map's starting view fits your tracked devices' latest fixes, or your saved places when none has reported yet, instead of always opening on a hardcoded US-centred view regardless of where your trackers actually are.
- The bottom tab bar on a phone-width dashboard stays clickable once the page is scrolled, instead of the map's overlay layer painting over it.
- The bundled icon sprite no longer leaves a blank band above the toolbar.
- The test suite's warning filters name the specific warnings Find+ suppresses, instead of ignoring every deprecation warning.
- `findplus devices --json` prints the device list as JSON, as the CLI reference documents.
- `GET /api/devices` rows carry the `groups` and `presence` keys the API contract documents.
- The menu bar shows a "CLI daemon vX (app is vY)" line when the daemon and the app disagree on version, instead of only writing it to the log.
- An alert rule whose channel has no credentials now records a `skipped` delivery instead of silently discarding the event.
- `GET /api/places/events?group_id=` returns that group members' events instead of always returning an empty list.
- `install.sh` no longer aborts with a `/dev/tty` error where no terminal is readable, such as inside a container.
- The MCP server instructions name both Google Find Hub and Apple Find My, instead of claiming every tracker reports through Find Hub.
- `findplus serve --host` now refuses a non-loopback address unless `FINDPLUS_ALLOW_PUBLIC_BIND=1` is set, matching `findplus config set HOST` and the `Settings.host` guard.
- The daemon answers 503 with the repair command on an unmigrated database, instead of 500.
- The dashboard no longer breaks when `/api/config` returns an error while the notices are loading.
- A group crossing recorded twice in the same instant is stored once, and the duplicate no longer discards the rest of the poll's location history.
- Upgrading a database that already contained duplicate group events now succeeds instead of leaving the daemon unable to start.
- The widget's large view hides the map for a device whose last fix is stale, and the small view no longer shows buttons it cannot action.
- The dashboard footer names each tracking network only when a device of that kind is tracked, instead of naming Google Find Hub for every tracker, and clears both sentences while the app is locked.
- The page sources behind the dashboard are no longer reachable under `/static`, in any capitalisation.
- An alert delivery error is stored with credentials masked, so a webhook key in a failing request URL is not shown in the Delivery log.
- A group whose members have mostly gone quiet is no longer labelled "Diverged" when only one is still reporting.
- Every stale group member shows how long since its last fix, instead of "no fix for unknown".
- The dashboard and the MCP server name the tracking network each device actually uses, instead of naming Google Find Hub for every tracker.
- "Refresh from your providers" now asks every provider you are signed in to, and says which one it could not reach instead of showing a raw error.
- Alerts carry the documented latency sentence, and a long group note is kept whole rather than cut mid-sentence.
- GPX and KML exports carry a device's label, falling back to its device ID when no label is set, instead of leaving the name and description blank.
- A CallMeBot phone number is now redacted in logs and CLI output, instead of appearing in the clear next to the API key.
- The widget shows the device with the newest fix rather than the first by name, spells a long gap in days, and names group verdicts the way the dashboard does.
- The lock screen states that locking does not encrypt the database, which until now was only visible in Settings, behind the lock.
- The Delivery log shows times in your local timezone and says why an alert was skipped.
- The group presence lists say which members are together and which are away.
- The installer pins the released version, tells you when `~/.local/bin` is not on your PATH, names the package to install when `venv` is missing, and rebuilds a virtualenv whose Python has gone.
- The macOS app bundle no longer carries the repository's editor configuration files.
- The Homebrew formula points at the release the tag actually published.
- The Windows scheduled task no longer kills the daemon every hour. Its time limit was capped at one hour by mistake; it now runs unlimited, like the macOS and Linux service managers already did.
- A database upgrade that adds columns to `devices`, `groups` or `alert_rules` no longer deletes rows from related tables such as group members and alert rules along the way.
- Downgrading a database that already has WhatsApp or Mac-notification alert deliveries in it no longer fails; those rows are remapped to their nearest 1.0 status instead of blocking the migration.
- A Telegram bot token or CallMeBot API key that is malformed, for example from a hand-edited config file, is rejected before Find+ ever sends it anywhere, instead of being placed into a request URL.
- A cross-site form post that carries a Referer header but no Origin or Sec-Fetch-Site header, such as one aimed at registering an Apple accessory, is now refused like any other cross-site request.
- The setup wizard renders inside a proper card with the same field and button styling as the rest of the app, instead of raw, unstyled rows, and offers WhatsApp as an inline setup step alongside Telegram.
- A group's CSV, JSON, GPX and KML exports now carry each member's label, falling back to its device ID when no label is set, the same as a single device's export already did.
- Pressing Next on the setup wizard's app lock step with a PIN typed and confirmed now sets it, instead of silently discarding it; a mismatched pair shows an inline error and stays on the step instead of advancing with no lock set.
- Apple Find My fixes carry the accuracy the source actually gives, which is none: Find+ no longer invents a metres figure from Apple's confidence label. The dashboard now shows "Accuracy unknown" for these fixes instead of a made-up `±N m` reading, and a database upgrade nulls out any invented figures a previous version already stored. A saved place's own accuracy, when copied from an invented Apple observation, is nulled by the same migration.
- Map marker popups show the tracker's display name as the heading, instead of the time.
- Devices, groups, the map, the timeline and the macOS widget now read a device or group's label before its raw provider name almost everywhere that still showed the raw name: the Edit button and dialog title, group presence sentences, and the widget's device rows and letter badges.
- The place dialog's tracker picker no longer lists every device twice the first time "Add place" is opened, and picking a tracker's location or an address-search result now shows "Location set from <name>." and pans the map to it.
- The setup wizard's device-label input no longer gets squeezed unreadable at 375px width.
- The wizard's Places step refreshes its list and re-fits the map after a place is added, instead of showing a stale list until the wizard reopens.
- The wizard's alerts-latency notice shows once, instead of once per channel, and the Telegram token field is wide enough to show its placeholder.
- The dashboard tabs sit in a navigation landmark with a `tablist` role, and the alerts tab's scrollable tables carry an explicit region role, for screen readers.
- Alert text shows a fix's time in local time with its zone, instead of a bare timestamp.
- The place dialog's Search/Use buttons and the place card's Edit/Delete buttons use the app's own button styling instead of unstyled browser defaults.
- Timeline rows show the saved place name for a fix inside it, instead of only its coordinates.
- The alerts Delivery log is readable at 360px as labelled cards instead of a squeezed table; a channel with no stored credentials is flagged instead of silently disabled, so a fresh install can still create its first rule; and a rejected Telegram token's raw server detail is replaced with a plain-language message.
- The wizard's Devices step gets a visible "Track" column header, every device defaults to ticked on a fresh account with nothing tracked yet, and pressing Next with nothing ticked asks for confirmation first instead of silently tracking nothing.
- The wizard's sign-in step has a heading, and the Google button reflects whether you are already signed in.
- The wizard's "configure later" webhook link opens the Alerts tab, instead of pointing at a dead Settings anchor.
- The wizard's summary step shows how many devices were actually tracked, and both the wizard and dashboard group dialogs block saving a group with no members selected, instead of showing "Unknown" with no explanation.
- Declining sign-in during `findplus setup` leaves onboarding open to resume later, instead of marking it complete.
- The dashboard no longer fires authenticated API calls, and no longer logs 401 errors, while Find+ is locked.
- The custom-icon upload starts as soon as a file is chosen, instead of requiring a separate Upload click.
- The phone-width tab bar draws its icons from the app's own SVG sprite instead of emoji glyphs, which rendered inconsistently across platforms and fonts.
- The poll-interval field in Settings shows a plain-language message next to the field when the value is out of range, instead of the raw config error at the top of the dialog.
- Chrome detection matches the same install locations the underlying Google Find Hub library searches, and the missing-Chrome notice only shows when Chrome is actually needed, instead of by default.
- The alerts rule dialog is titled and styled like the place/group/device dialogs, defaults its channel checkboxes to whichever are actually connected instead of always ticking Telegram, and refuses to save a rule with nothing connected selected.
- Every inline style the delivery log's column widths used is in CSS now, clearing the console errors they caused under the dashboard's Content-Security-Policy.

- Alerts rules render as stacked cards inside the narrow side pane, with Edit and Delete inside it, instead of a table too wide for the pane to show.
- Places, Groups and the macOS widget now agree on one staleness window, instead of Places and the widget using a 90-minute cutoff while a group's own cutoff disagreed with no explanation.
- The Delivery log shows the sent text and body for every channel, not only desktop notifications; a WhatsApp row no longer claims its message "is not logged" when it is.
- A stale group member's note counts minutes up to two hours, instead of rounding "94 minutes" straight to "1 h".
- The Chrome-not-found notice on the sign-in step and in Settings shows only when you are actually signed out and Chrome is missing, instead of also showing while you are signed in.
- Settings shows a Switch account button once you are signed in to a provider.
- The More menu closes on Escape or a tap outside it, and returns focus to the More button.
- The More menu's Lock item is hidden until a PIN is actually set, instead of opening a lock screen that any PIN dismisses.
- The group dialog's cluster-radius hint sits on its own line under the slider instead of squeezed beside it, and a group card's Edit and Delete buttons share one row instead of wrapping.
- The Groups tab's presence panel refreshes after you save or delete the selected group, instead of showing the old verdict until you reselect it.
- `alerts deliveries` and `alerts rules list` print local time and a plain yes/no, instead of raw UTC timestamps and Python's True/False.
- The wizard's token, phone, API key and device-label fields carry accessible names for screen readers, and the phone field shows an example number.
- The wizard's welcome step says plainly what leaves the machine (sign-in, alert channels you connect, map tiles, and opt-in address search) instead of a blanket claim that nothing does except Google or Apple sign-in, and no longer lists map tiles among the things you turn on, since they always load.
- The first-run wizard's map shows your tracked devices' latest fixes before the dashboard has ever booted, instead of only place circles with no trackers on it; its zoom and attribution controls are readable in dark mode.
- The wizard's Groups step name field has a visible label, and its app-lock step shows a PIN error next to the field instead of a plain-grey line below the whole form.
- The wizard's Done step shows the real tracked-device count after a reload resumes it partway through, instead of "0 devices tracked".
- The wizard's Groups and Devices steps show their own errors inline instead of writing them to a hidden banner, so a duplicate group name or a failed device save is no longer silent.
- Saving a place or group whose name is already in use shows a plain sentence instead of the raw server error.
- Poll Now disables itself for the remaining cooldown instead of letting a second click fail with a console error.
- The wizard's Places step gives its Add place button room above the map instead of sitting flush against it.
- `findplus status` checks the daemon's own bound port, instead of the default, so it reports correctly when the daemon runs on a custom port.
- Settings' confirm-PIN field is linked to its mismatch error for screen readers, and a new PIN attempt clears the old top-of-dialog message instead of leaving it next to the new field error.
- The phone-width topbar's More label sits centred in its button, instead of pinned to the top.

### Security
- The local API's Host and Origin checks now also require the daemon's own bound port, not just the loopback hostname, closing a DNS-rebinding gap where a page could name any port it liked and still get past the guard. The check reads the port the daemon actually bound to, not a config value that could change while it runs.

## [1.0.0] - 2026-09-19

### Added
- Location history daemon for Google Find Hub trackers (Moto Tag and compatible).
- Apple Find My support for accessories whose pairing keys are available (optional `findplus[apple]` extra).
- FastAPI HTTP server at http://127.0.0.1:8647 with a vanilla-JS dashboard including an interactive Leaflet map.
- SQLite database via Alembic migrations; automatic schema upgrade on start.
- Click CLI: auth, devices, poll-now, serve, start, stop, restart, status, doctor, open, export, prune, config, db, providers, places, groups, alerts, mcp, version, widget.
- User-level service management via LaunchAgent (macOS), systemd user unit (Linux), and Task Scheduler (Windows).
- Places and geofence alerts: circular geofences with configurable enter/exit confirmation counts and hysteresis.
- Group presence tracking with quorum semantics (any/majority/all/N), cluster radius, and stale-after threshold.
- Telegram bot alerts with long-poll setup flow and webhook alternative.
- MCP server (stdio) exposing location, place, group, and alert query tools to LLM clients.
- macOS menu-bar app (Tauri 2) with a WidgetKit widget showing live device and group presence.
- PyInstaller sidecar bundled inside the macOS app.
- App lock with PIN; lock does not encrypt the database (see Privacy).
- Multi-provider architecture: pluggable provider interface for future tracker support.
- CLI export to CSV, JSON, GPX, and KML with group support (one track per member).
- `findplus doctor` with --repair flag; `findplus version --check` against GitHub releases.

[Unreleased]: https://github.com/acamarata/findplus/compare/v1.1.5...HEAD
[1.0.0]: https://github.com/acamarata/findplus/releases/tag/v1.0.0
