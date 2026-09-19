# Find+ P1 handoff

Written by the E15-T5 builder (ticket P1-E15-W9-S1-T5) on 2026-09-19 from the E15 evidence artefacts:
`.claude/phases/current/p1/e15/gate-run-log.md`, `review-log.md`, `rehearsal-log.md` and
`screenshots/MANIFEST.txt`. Every command below was run on this machine unless section 2
says otherwise.

## 1. Proven, verified locally by the agent

| Command | What it proves | Evidence source |
|---|---|---|
| `./.venv/bin/python -m pytest cli/tests/ -q` | the whole suite passes, 991 tests | gate-run-log.md, macOS step a |
| `./.venv/bin/python -m pytest cli/tests -q -m browser` | the 29 Playwright tests pass against bundled Chromium | gate-run-log.md, macOS step b |
| `./.venv/bin/ruff check cli/src cli/tests` | zero lint warnings | gate-run-log.md, macOS step c |
| `./.venv/bin/ruff format --check cli/src cli/tests` | formatting is clean | gate-run-log.md, macOS step d |
| `shellcheck install.sh` | the installer is clean | gate-run-log.md, macOS step f |
| `cargo test --manifest-path desktop/src-tauri/Cargo.toml` | 19 Rust unit tests pass | gate-run-log.md, macOS step j |
| `cargo clippy --manifest-path desktop/src-tauri/Cargo.toml --all-targets -- -D warnings` | the Tauri shell has no clippy warnings | gate-run-log.md, macOS step i |
| `xcodebuild -project desktop/widget/FindPlusWidget.xcodeproj -scheme FindPlusWidgetExtension -configuration Release -arch arm64 build CODE_SIGNING_ALLOWED=NO -derivedDataPath desktop/widget/build` | the widget builds | gate-run-log.md, macOS step k |
| `xcodebuild test -project desktop/widget/FindPlusWidget.xcodeproj -scheme FindPlusWidgetTests -destination 'platform=macOS' -derivedDataPath desktop/widget/build` | 22 widget tests pass | screenshots/MANIFEST.txt |
| `./.venv/bin/python -m coverage report --fail-under=95 --include='cli/src/findplus/places/geofence.py,cli/src/findplus/groups/presence.py,cli/src/findplus/groups/quorum.py,cli/src/findplus/alerts/dispatch.py,cli/src/findplus/alerts/dispatch_core.py'` | the critical path is at 98 percent | gate-run-log.md, macOS step m |
| `docker run --rm -v "$PWD":/repo -w /repo python:3.12 bash -c "pip install -q -e cli/[dev] && python -m pytest cli/tests -q -m 'not browser and not slow'"` | Linux passes, 914 tests | gate-run-log.md, Linux |
| `bash packaging/scripts/rehearse-fresh-machine.sh all` | a machine with only Python installs, runs, reinstalls and uninstalls Find+ | rehearsal-log.md |
| `grep -c ' FAIL' .claude/phases/current/p1/e15/rehearsal-log.md` | zero rehearsal failures | rehearsal-log.md |
| `ls .claude/phases/current/p1/e15/screenshots/MANIFEST.txt` | tray captures exist for all five states | screenshots/MANIFEST.txt |
| `grep 'T2 STATUS' .claude/phases/current/p1/e15/review-log.md` | the review loops' state, read before the release ticket ran | review-log.md |

## 2. Unproven, requires owner action

| Item | Why unproven | Required action |
|---|---|---|
| Google Find Hub sign-in | needs a real Google account and an interactive Chrome session | run `findplus auth` in your own session |
| Apple Find My key extraction | needs physical accessory pairing | run `findplus auth --provider apple-find-my` with your Apple ID |
| Real device location polling | depends on the Google sign-in above | run `findplus poll-now` after auth |
| PyPI publish | `PYPI_API_TOKEN` is absent from `~/.claude/vault.env` | add the token, then run `./.venv/bin/twine upload dist/findplus-1.0.0*` |
| Homebrew tap install | the tap holds only a LICENSE until the release ticket pushes the formula | run `brew install acamarata/tap/findplus` after the release |
| Notarisation on a clean machine | this machine signs with its own keychain identity | set the `APPLE_API_KEY_*` secrets in the repo and run `release.yml` |
| dmg size against the 120 MB budget | measurable only after the signed build | run `du -h dist/FindPlus-1.0.0-aarch64.dmg` |
| Intel dmg | no x86_64 hardware or runner | build on an Intel Mac, or leave arm64 as the only artefact |
| The six GUI steps in `.github/docs/REHEARSAL.md` | need a real desktop session | follow that checklist once |

## 3. Honesty text status

Every sentence lives once, in `cli/src/findplus/honesty.py`, and reaches the dashboard through
`/api/config`. `web/index.html` carries a keyed empty element for each, and `web/app/notices.js`
fills it, so the rendered text cannot drift from the source.

| Key | Sentence, first 60 characters | In index.html | In test_honesty_text.py | Verified |
|---|---|---|---|---|
| find_hub | `This history consists of locations reported through Google's` | yes, `id="fp-notice-find-hub"` | yes | yes |
| apple | `Apple Find My locations come from nearby Apple devices and c` | yes, `id="fp-notice-apple"` | yes | yes |
| alerts_latency | `Alerts inherit the network's delay. An arrival or departure ` | yes, `id="fp-notice-alerts-latency"` and `id="fp-alerts-latency-notice"` | yes | yes |
| presence_stale | `A tag with no recent fix is stale, not at home and not left ` | yes, `id="fp-notice-presence-stale"` | yes | yes |
| lock_not_encryption | `The app lock stops casual browsing. It does not encrypt the ` | yes, `id="fp-notice-lock"` | yes | yes |
| not_affiliated | `Find+ is not affiliated with Apple or Google. Find Hub and F` | yes, `id="fp-notice-not-affiliated"` | yes | yes |

## 4. Known limitations

Widget, from `specs/widget.md`:

> WidgetKit refresh budget (Apple decides when timelines reload; 15-minute minimum in practice); no live map; first render after install may take up to a minute.

Lock, verbatim from `honesty.py`:

> The app lock stops casual browsing. It does not encrypt the database; anyone with access to
> this user account or the disk can read it. Use FileVault.

Other limits the E15 work established:

- The tray menu opens through the accessibility tree during capture but does not stay on screen
  for `screencapture`, so `screenshots/tray-*.png` show the status item and its dot colour, and
  `screenshots/menu-*.txt` hold the menu text read at the same moment.
- The widget test target writes no XCTAttachment images, so there are no widget screenshots.
- The Homebrew formula's only `brew style` complaint is `FormulaAudit/PyPiUrls`, which stands
  until the sdist is on PyPI.
- Dependabot PRs 1 to 5 are parked until after v1.0.0. `review-log.md` records that four of them
  are safe as they stand and that `actions/upload-artifact@v4` to v7 needs
  `if-no-files-found: warn` set on `release.yml`'s finalise step before it is merged.
- Windows is unit-tested and CI-tested, never run on real hardware, so it ships labelled as
  community-tested.

## 5. How to continue

```
bash packaging/scripts/rehearse-fresh-machine.sh all
./.venv/bin/python -m pytest cli/tests/ -q
gh release view v1.0.0 --json assets --jq '.assets[].name'
brew install acamarata/tap/findplus
findplus auth
findplus poll-now
findplus start --yes
open http://127.0.0.1:8647/
```

Run them in that order. The first two re-prove the tree, the next two check what the release
ticket published, and the last four sign in, take a first real fix, install the background
service and open the dashboard.
