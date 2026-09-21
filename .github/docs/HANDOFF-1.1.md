# Find+ P2 handoff (1.1.0)

Written by the E13-T6 builder (ticket P2-E13-W6-S1-T6) on 2026-09-21 from the E13 evidence
artefacts that actually exist in the tree at write time. `specs/release-1.1.md` §4.1 names a
`qa-done/{gate-run-log.md,review-log.md,adversarial-log.md}` set; that directory was never
created. E13-T1 (full gate run, loop 1), E13-T2 (loop 2, spec-vs-implementation) and E13-T3
(adversarial cap) are still `status: pending` in their ticket YAML at write time, so the closing
lines those files would have held (`Loops complete: 3/3. Blockers open: 0.` and `Adversarial
pass: CLEAR`) do not exist yet either. The rows below cite the real files that do exist:
`crunch/build-notes.md`, `e13/loop1-inputs.md`, `e13/loop2/review-B.md`, `e13/loop2-inputs.md`,
`e13/blind-gp-adjudicated.md`, `e13/rehearsal-log-T4.md`, `e13/linux-rehearsal/REPORT.md`,
`events/progress.jsonl` and `events/E13.jsonl`. Each row states what it actually shows,
not what the spec assumed it would show.

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

**Status of the three review loops (E13-T1/T2/T3) at write time**: not closed. Loop 1's two GP
passes landed and were re-verified by T0 in a clean worktree, but the `P2-E13-W6-S1-T1` ticket
itself is still `pending`. Loop 2's review B (Sonnet) finished and its findings are fixed; reviews
A and C were dispatched twice on the GP and Za lanes and both attempts failed before producing a
finding (`e13/loop2/review-A.md` and `review-C.md` are empty; `review-A.err`/`review-C.err` show
`RESOURCE_EXHAUSTED` quota errors, and a later retry hit an unrecognised-model error for
`glm-5.3`). See `e13/loop2-inputs.md` for the L2/L3 items still open. The adversarial cap's GP
lane finished two passes and T0 adjudicated every finding; a third, cross-family Za lane started
(`events/E13.jsonl`, 02:50:20Z) but no completion or `Adversarial pass:` line is recorded yet. The
most recent push, commit `59531d3` (CI run 35555670529), was still queued at write time; the two
pushes before it failed CI (`8b11486` on utf-8 file reads and an a11y dialog timeout, `05dd506` on
a stale service import) and were each followed by a fix commit. Whoever runs E13-T1/T2/T3 to
completion should re-verify every row above against `main`'s tip at that time, not assume this
table still matches.

**Addendum (loop 3, 2026-09-21)**: the sentence above about reviews A and C is stale. Both
finished after this doc was written: `e13/loop2/review-A.md` (blocking 0, major 3, minor 2) and
`e13/loop2/review-C.md` (blocking 0, major 4, minor 2) are populated, and their findings (A1-A5,
C1-C6) drove 19 of loop 2's 30 commits. Loop 3's own review (`e13/loop2/review-L3.md`) closed
with blocking 0, major 1, minor 2.

## 2. Unproven, requires owner action

| Item | Why unproven | Required action |
|---|---|---|
| Publishing the v1.1.0 draft release | owner_only, public_identity boundary | open the draft on GitHub and click Publish |
| Merging release/1.1.0's version-bump commit to main | stays on the branch until published, per D-P2-14 | merge after publishing |
| Updating the acamarata/homebrew-tap formula | owner_only | copy packaging/homebrew/findplus.rb to the tap and push |
| PyPI upload | deferred every release per §3.5, never uploaded within a draft ticket | run twine upload after publishing |
| Registering a real WhatsApp number with CallMeBot | each user does this for themselves | send the CallMeBot opt-in text from the user's own phone |
| Real Google or Apple sign-in | rehearsal uses the fixture stub (T4); live sign-in needs a real account | run findplus auth from the dashboard once installed |

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

- The icon picker offers a fixed set of 48 Lucide ids; there is no custom icon upload (`specs/labels-and-icons.md` § Lucide subset).
- Native notifications are macOS only. On Linux and Windows the dashboard's channel picker omits the `native` option entirely, because `GET /api/version.platform` does not report `macOS`; the backend still accepts and stores a `native` channel from a synced config, it just has no poller to consume it there (`specs/notifications.md` § Linux/Windows).
- WhatsApp alerts depend on CallMeBot, a third-party free service, staying up. CallMeBot enforces a personal-use rate limit and always answers `200` with a plain-text body, so a throttled send and a bad credential cannot be told apart from the response alone (`specs/notifications.md` § Rate limit, § Response handling).
- Windows and Linux ship no desktop app or widget in this phase. That is a stated non-goal, not a gap (`specs/release-1.1.md` § 4.2).
- `gh release create --draft` creates no git tag. `git ls-remote --tags origin v1.1.0` returning nothing before the owner publishes is expected, not a defect (`specs/release-1.1.md` § 3.7).

## 5. How to continue

a. Review `.claude/phases/current/p2/release/draft-release-log.md` (P2-E13-W6-S1-T7's output).
b. Open the draft release URL and click Publish: https://github.com/acamarata/findplus/releases/tag/untagged-f85e26032810e6eed002 (draft; release/1.1.0 @ 63a8800; 5 assets, notarised arm64 dmg 51 MB)
c. `git checkout main && git merge release/1.1.0 && git push origin main`. This merges the version bump only after publishing, per D-P2-14.
d. Update the Homebrew tap: `cp packaging/homebrew/findplus.rb <tap-clone>/Formula/findplus.rb`, commit, push.
e. Run the wizard for a real first run: install Find+, open it, sign in with a real account.

Final gate counts (full suite, CI lane parity, review-loop and adversarial-cap closure): non-browser 1677 passed, browser 215 passed, slow 2 passed; ruff, node, shellcheck, gen-* drift clean; clippy 0 warnings, cargo tests green, widget 43; CI run 35562428139 green on 57c57df; three QA loops closed (A 5, B 7, C 6, L3 3 findings fixed), blind cap 2 Gemini + 1 Sonnet passes adjudicated
