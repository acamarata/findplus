# Find+ P2 handoff (1.1.0)

Written by the E13-T6 builder (ticket P2-E13-W6-S1-T6) on 2026-09-21, from the E13 evidence
artefacts that existed in the tree at that time. Refreshed 2026-09-23 to cover the closeout
round that landed on `main` after the draft release was cut (see §1a) and to correct the stale
claim §1 used to make about reviews A/C (finding `L3R2`, `e13/loop2/review-L3.md`). Everything
below describes the state of `main` as of this refresh, not a point-in-time snapshot.
`specs/release-1.1.md` §4.1 names a `qa-done/{gate-run-log.md,review-log.md,adversarial-log.md}`
set; that directory was never created. The rows below cite the real files that do exist:
`crunch/build-notes.md`, `e13/loop1-inputs.md`, `e13/loop2/review-{A,B,C,L3}.md`,
`e13/loop2-inputs.md`, `e13/blind-gp-adjudicated.md`, `e13/rehearsal-log-T4.md`,
`e13/linux-rehearsal/REPORT.md`, `events/progress.jsonl` and `events/E13.jsonl`. Each row states
what it actually shows, not what the spec assumed it would show.

## 1. Proven

| Command | What it proves | Evidence source |
|---|---|---|
| `./.venv/bin/python -m pytest cli/tests -q -m 'not browser and not slow'` | non-browser suite passes; 1669 passed as of the most recent recorded run | `events/progress.jsonl` (`P2-E13-W6-S1-T4` accepted line, 02:54:13Z), `e13/rehearsal-log-T4.md` |
| `./.venv/bin/python -m pytest cli/tests -q -m browser` | Playwright suite passes against bundled Chromium; 212 green with one known intermittent flake (`test_alerts.py::test_webhook_save`, 30x green in isolation) | `events/progress.jsonl` (`loop2 L2-7/8/9` fix_done note, 02:18:58Z) |
| `./.venv/bin/ruff check cli/src cli/tests` and `./.venv/bin/ruff format --check cli/src cli/tests` | lint and format clean | `crunch/build-notes.md` § E13 fix-agent (loop2, commit `af601bb`) |
| `bash packaging/scripts/stage-sidecar-stub.sh && cargo test --manifest-path desktop/src-tauri/Cargo.toml` | 62 Rust unit tests pass in a clean worktree; the sidecar stub step is required first because `desktop/src-tauri/resources/findplus-daemon/` is gitignored and `tauri_build` validates the bundle resources glob on every clippy/test | `crunch/build-notes.md` § E13 fix-agent (loop2, Defect 1, commit `4966962`) |
| `xcodebuild -scheme FindPlusWidgetExtension -destination "generic/platform=macOS" build CODE_SIGNING_ALLOWED=NO` (from `desktop/widget`) | widget builds; 41 widget tests green | `events/progress.jsonl` (gate line, sha `a95268f`) |
| `bash packaging/scripts/rehearse-first-run.sh` | first-run wizard works end to end against a fixture Google sign-in and the real daemon; exits 0, final line `REHEARSAL-FIRST-RUN-PASS` | `e13/rehearsal-log-T4.md` |
| `ls .github/docs/screenshots/setup/*.png \| wc -l` | 16 setup screenshots captured (8 steps times 2 widths, 1280px and 375px) | `.github/docs/screenshots/setup/MANIFEST.txt` |
| `docker run --rm -v "$PWD":/repo -w /repo python:3.12 bash packaging/scripts/rehearsal-linux-inner.sh` | headless `findplus setup --yes` first run works on Linux; `onboarding.last_step` is `"headless"` and `onboarding.completed_at` stays null (R-P2-24) | `e13/linux-rehearsal/REPORT.md` |
| gate-before full run (Za, pre-loop-1) | 1614 passed; ruff, `node --check`, `cargo clippy`, `cargo test` (62), widget build all green before loop 1 started | `events/E13.jsonl` (waypoint, `P2-E13-W6-S1-T1`, 01:09:22Z) |
| loop 1 fixes | two GP passes landed 13 py/rust/swift/ci fixes (commit `d2403b2`) and 10 js/css/docs/spec fixes plus 2 spec amendments (commit `000bb2e`); both verified against the current tree, not trusted from notes alone | `e13/loop1-inputs.md`, `crunch/build-notes.md` §§ E13-T1 loop 1 |
| loop 2 review B (Sonnet, spec-vs-implementation) | 1 blocking and 6 major/minor findings, all fixed (commits `4ba0912`, `5e80f9f`, `e93ccff`, `dc86bf7`, `2181859`, `cb33763`) | `e13/loop2/review-B.md`, `events/E13.jsonl` (waypoint, 01:48:01Z) |
| adversarial cap, GP lane (two passes) | 12 findings triaged: 3 accepted and fixed, 1 false positive (verified against the pinned spec, no code change), the rest routed to the wizard agent or already covered by loop 1 | `e13/blind-gp-adjudicated.md` |

**Status of the three review loops (E13-T1/T2/T3), as they closed**: loop 1's two GP passes
landed and were re-verified by T0 in a clean worktree (commits `d2403b2`, `000bb2e`). Loop 2 ran
all three reviews: review B (Sonnet, spec-vs-implementation) found 1 blocking and 6 major/minor
findings, all fixed (commits `4ba0912`, `5e80f9f`, `e93ccff`, `dc86bf7`, `2181859`, `cb33763`);
review A (blocking 0, major 3, minor 2) and review C (blocking 0, major 4, minor 2) -- both
dispatched twice before producing output (`RESOURCE_EXHAUSTED` quota errors, then an
unrecognised-model error for `glm-5.3`) -- eventually populated `e13/loop2/review-A.md` and
`review-C.md`, and their findings (A1-A5, C1-C6) drove 19 of loop 2's 30 commits. Loop 3's own
review (`e13/loop2/review-L3.md`) closed with blocking 0, major 1, minor 2, including this
paragraph's own predecessor (`L3R2`: the doc self-contradicted about whether A/C had finished --
fixed by this refresh). The adversarial cap's GP lane finished two passes, T0 adjudicated every
finding (`e13/blind-gp-adjudicated.md`), and a third cross-family Za lane ran to completion.
Ticket YAML `status:` fields for T1/T2/T3 were never flipped to `done` (an administrative gap,
not a QA gap -- see `.claude/phases/current/p2/e13/open-ledger.md`, which re-verified every open
item against the tree on 2026-09-22).

## 1a. Closeout round (after the draft branch point, `63a8800`..`HEAD`)

The draft v1.1.0 release was cut from `release/1.1.0` at `63a8800`. Four more UAT walks (UAT2
through UAT5), two GP reviews of the fixes each round produced, a Linux clean-install check, two
Windows CI failures, and three release-script bugs found while building the draft dmg all landed
on `main` afterwards and are not in the cut draft. **The draft must be re-cut from current `main`
before publishing** (see §5). Round-by-round counts: `.claude/phases/current/p2/PHASE-REPORT.md`
§Closeout rounds. Nothing below is published; the dmg on the existing draft still predates all of
it.

**Re-cut draft: <pending>**

Highlights, grouped by what a user would notice:

- **Security**: the local API's Host/Origin guard now also checks the daemon's own bound port
  (`a550c79`, `81592a6`, `31b628c`), closing a DNS-rebinding gap where a page naming any port
  still passed the loopback-hostname check.
- **Honesty**: Apple Find My fixes with no reported accuracy are stored and shown as
  "Accuracy unknown" instead of an invented `±N m` figure; migration 0009 nulls any such figure
  a previous version already wrote, and a follow-up (`e962bbb`) closes the same gap for
  `place_events` accuracy copied from an invented Apple observation.
- **Alerts**: failed Telegram/WhatsApp/webhook deliveries now retry automatically on a
  temporary-looking failure (migration 0010, `cca2645`, `841b3ef`); alert text renders in local
  time with its zone (`76b52a3`); the delivery log is readable at 360px and flags an unconfigured
  channel instead of silently disabling it (`72c48e8`); the rule dialog is styled and defaults to
  actually-connected channels instead of an always-ticked Telegram (`d29a5a6`).
- **Places**: the tracker picker no longer lists every device twice on first open, and picking a
  tracker or an address-search result now shows confirmation text and pans the map (`f76875e`);
  timeline rows show the saved place name for a fix inside it, not just coordinates (`c2a65ee`,
  UAT U30b).
- **Labels**: device/group edit dialogs, map popups, presence text and the macOS widget read a
  device's label before its raw provider name almost everywhere that still showed the raw name
  (`91934cd`, `2c9be82`, `ae7c419`); `findplus alerts rules list` and `findplus devices` do the
  same in the CLI (`c46d204`).
- **Icons**: a custom PNG upload now starts as soon as a file is chosen, instead of a separate
  Upload click (`0fdd0b5`); the icon subset gained a `bell` glyph (49 total) and the phone tab bar
  uses it instead of emoji (`ce522d8`).
- **Setup wizard / CLI**: `findplus lock reset` is a new, more discoverable name for the existing
  PIN-recovery command, and a wrong PIN now shows the real error with a pointer to it (`46aa952`);
  `findplus start` prompts for confirmation in an interactive terminal instead of requiring
  `--yes` (`b03ced9`); `findplus devices` lists from the local database by default, `--refresh`
  opts into a live query; the wizard's device-count summary, sign-in step heading, "configure
  later" webhook link, zero-member group guard, and declined-sign-in handling were each fixed
  against their UAT findings (`7cc1da1`, `014866d`, `21fc7b9`, `ead10c3`).
- **Accessibility**: the dashboard tabs sit in a navigation landmark with a `tablist` role, and
  the alerts tables carry an explicit `region` role (`bf4c8ea`, `b8a467f`).
- **Boot**: the dashboard no longer fires authenticated fetches (and logs 401s) while locked
  (`e444f60`); a missing `alerts_rule_channels.js` module that broke the dashboard boot on a
  clean checkout is restored (`76327e6`).
- Every CSP-relevant style moved out of inline attributes; a new browser test fails on any CSP
  console error across every tab, at both widths (`d29a5a6`).
- **UAT3-UAT5 (three more walks, 37 findings, all fixed)**: the alerts rules table becomes a
  card list instead of overflowing its pane (`96c9383`); Places, Groups and the widget now agree
  on one staleness window (`a9cbda5`, `2c9be82`); the Delivery log renders text and body for every
  channel, not just desktop notifications (`a9cbda5`, `d99965b`); the Chrome-not-found notice only
  shows when you're actually signed out (`2330fac`); the More menu closes on Escape or an outside
  tap (`6d317ea`); alert tables print local time and yes/no instead of raw UTC/`True` (`2330fac`);
  the wizard's welcome step states plainly what leaves the machine and stops calling map tiles a
  thing you turn on (`7a83aef`, `5e8fa0b`); `findplus status` probes the daemon's own bound port
  instead of the default (`5cb3203`); the More menu's Lock item is hidden with no PIN set
  (`30c6fd7`); duplicate place/group names get a plain-language error instead of a raw 409
  (`5cd6c83`); Poll Now disables itself for its cooldown instead of racing a 429 (`4b5782b`); the
  wizard's Groups/Devices steps show their own errors instead of a hidden banner (`0ec1fbc`); the
  wizard's Add place button gets breathing room above the map (`ebcebd5`); Settings' confirm-PIN
  error is linked for screen readers (`3d57ea0`); `alerts deliveries` gained `--json` and channel
  names read "Desktop notification"/"WhatsApp" instead of raw ids (`101548e`).
- **Linux and Windows**: a clean-install check on Linux found `findplus stop` claiming "Stopped."
  with no service installed, and `install.sh`'s Python-floor error naming neither the version it
  found nor a fix, both corrected (`b37e97a`, `LINUX-1`). Windows CI turned up two real bugs, not
  test-only gaps: `time.tzset()` doesn't exist on Windows, so alert-message tests errored on every
  run until local time was read through a seam tests can pin directly (`fc8563c`); and Chrome
  detection had no win32 branch at all, so the Settings sign-in card would always say Chrome was
  missing on a real Windows install (`fc8563c`, `WINCI-1`/`WINCI-2`).
- **Release script**: three bugs found building the draft dmg, not by a review round. The
  `externalBin` sidecar launcher shipped unsigned, which the outer app-sign step rejected
  (`6089eae`); the root-level dmg + sha256 `release-local.sh` writes were left untracked and dirty
  after a real build (`2598326`); and the widget step built into the global DerivedData instead of
  `desktop/widget/build`, the path `embed-widget.sh` actually reads, so a stale appex could ship
  (`5414d1a`).
- **Gate hardening**: the local gate script now treats an all-skipped browser or a11y lane (every
  test skipped, nothing passed) as a Chromium-missing failure instead of reporting a false green.

## 2. Unproven, requires owner action

| Item | Why unproven | Required action |
|---|---|---|
| Re-cutting the v1.1.0 draft release from current `main` | the existing draft was cut at `63a8800`, before the closeout round in §1a | re-run the release-cut ticket's steps (bump, tag, build, notarise, draft) against current `main` |
| Publishing the re-cut v1.1.0 draft release | owner_only, public_identity boundary | open the draft on GitHub and click Publish |
| Merging the version-bump commit to main | stays on its branch until published, per D-P2-14 | merge after publishing |
| Updating the acamarata/homebrew-tap formula | owner_only | copy packaging/homebrew/findplus.rb to the tap and push |
| PyPI upload | deferred every release per §3.5, never uploaded within a draft ticket | run twine upload after publishing |
| Registering a real WhatsApp number with CallMeBot | each user does this for themselves | send the CallMeBot opt-in text from the user's own phone |
| Real Google or Apple sign-in | rehearsal uses the fixture stub (T4); live sign-in needs a real account | run findplus auth from the dashboard once installed |
| Deciding whether to re-cut a 1.0.1 | the published v1.0.0 dmg embeds `web/.claude/` (no secrets) inside the notarised app, fixed for 1.1; default is no -- 1.1 supersedes 1.0.0 | owner decides; see PHASE-REPORT.md item 5 |

## 3. Honesty text status

Every sentence lives once in `cli/src/findplus/honesty.py`'s `NOTICES` dict, iterated by
`test_honesty_text.py` and by `web/app/notices.js` rather than a hardcoded key list (R-P2-5
pins the count at eleven; `e13/loop2/review-B.md`'s clean-audit section confirms exactly eleven
keys, all present in `en.json`'s `honesty.*` block).

| Key | Sentence (first 60 chars) | In UI | In tests | Verified |
|---|---|---|---|---|
| find_hub | This history consists of locations reported through Goog | yes, `#fp-notice-find-hub` | yes | yes |
| apple | Apple Find My locations come from nearby Apple devices an | yes, `#fp-notice-apple` | yes | yes |
| alerts_latency | Alerts inherit the network's delay. An arrival or departu | yes, `#fp-notice-alerts-latency` and `#fp-alerts-latency-notice` | yes | yes |
| presence_stale | A tag with no recent fix is stale, not at home and not le | yes, `#fp-notice-presence-stale` | yes | yes |
| lock_not_encryption | The app lock stops casual browsing. It does not encrypt t | yes, Settings dialog `#lock-caveat` and the lock screen (not `notices.js`, by design; see its header comment) | yes | yes |
| whatsapp_relay | WhatsApp alerts are relayed through CallMeBot, a third-pa | yes, `#fp-wa-relay-notice` | yes | yes |
| whatsapp_setup | To connect WhatsApp: add +34 623 91 22 04 to your phone's | yes, `#fp-wa-instructions` | yes | yes |
| alerts_locked | Notifications are held while Find+ is locked. Unlock to s | yes, `#fp-alerts-locked-notice` | yes | yes |
| native_generic | By default, macOS notifications show a generic "Find+ ale | yes, rendered beside the native-detail settings toggle | yes | yes |
| not_affiliated | Find+ is not affiliated with Apple or Google. Find Hub an | yes, `#fp-notice-not-affiliated` | yes | yes |
| chrome_required | Google Chrome was not found on this machine. Google sign- | yes, `#fp-auth-chrome-notice` | yes | yes |

New UI strings the wizard restates from these entries (per D-P2-7 and `e13/rehearsal-log-T4.md`'s
recorded rehearsal): the Welcome step shows `not_affiliated` as a footnote; the Sign in step shows
`find_hub` under the Google heading and `apple` under the Apple heading; the Devices step shows
`presence_stale` as small print under the device list.

## 4. Known limitations

- The icon picker's bundled set is a fixed 49 Lucide ids (`specs/labels-and-icons.md` § Lucide subset); a custom PNG upload (16-512px, up to 64 KiB) covers anything the bundled set does not, but the macOS widget cannot fetch images, so a custom icon shows there as a letter badge instead.
- Native notifications are macOS only. On Linux and Windows the dashboard's channel picker omits the `native` option entirely, because `GET /api/version.platform` does not report `macOS`; the backend still accepts and stores a `native` channel from a synced config, it just has no poller to consume it there (`specs/notifications.md` § Linux/Windows).
- WhatsApp alerts depend on CallMeBot, a third-party free service, staying up. CallMeBot enforces a personal-use rate limit and always answers `200` with a plain-text body, so a throttled send and a bad credential cannot be told apart from the response alone (`specs/notifications.md` § Rate limit, § Response handling).
- Windows and Linux ship no desktop app or widget in this phase. That is a stated non-goal, not a gap (`specs/release-1.1.md` § 4.2).
- `gh release create --draft` creates no git tag. `git ls-remote --tags origin v1.1.0` returning nothing before the owner publishes is expected, not a defect (`specs/release-1.1.md` § 3.7).

## 5. How to continue

a. **Re-cut the draft from current `main`**: the existing draft (release/1.1.0 @ 63a8800) predates
   the closeout round in §1a. Re-run the release-cut ticket's steps -- version bump, tag, build,
   sign, notarise -- against current `main`, replacing the draft's assets rather than publishing
   the stale ones. `gh release view v1.1.0` still shows it as an unpublished draft targeting
   `release/1.1.0`.

   **Re-cut draft: <pending>**
b. Review `.claude/phases/current/p2/release/draft-release-log.md` (P2-E13-W6-S1-T7's output) for
   the exact steps the original cut followed.
c. Open the re-cut draft release on GitHub and click Publish (owner_only, public_identity boundary).
d. `git checkout main && git merge release/1.1.0 && git push origin main`. This merges the
   version bump only after publishing, per D-P2-14.
e. Update the Homebrew tap: `cp packaging/homebrew/findplus.rb <tap-clone>/Formula/findplus.rb`, commit, push.
f. Run the wizard for a real first run: install Find+, open it, sign in with a real account.
g. Decide whether to re-cut a 1.0.1 for the `web/.claude/` packaging gap (PHASE-REPORT.md item 5;
   default is no).

Gate counts at the original draft cut (`57c57df`, before the closeout round): non-browser 1677
passed, browser 215 passed, slow 2 passed; ruff, node, shellcheck, gen-* drift clean; clippy 0
warnings, cargo tests green, widget 43; CI run 35562428139 green; three QA loops closed (A 5, B 7,
C 6, L3 3 findings fixed), blind cap 2 Gemini + 1 Sonnet passes adjudicated. Whoever re-cuts the
release should re-run the full gate against current `main`'s tip rather than trust these counts.
