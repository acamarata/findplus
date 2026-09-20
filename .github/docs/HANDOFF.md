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
| `./.venv/bin/python -m coverage report --fail-under=95 --include='cli/src/findplus/places/geofence.py,cli/src/findplus/groups/presence.py,cli/src/findplus/groups/quorum.py,cli/src/findplus/alerts/dispatch.py,cli/src/findplus/alerts/dispatch_core.py,cli/src/findplus/alerts/dispatch_send.py'` | the critical path is at 98 percent | gate-run-log.md, macOS step m |
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

PyPI publish deferred: token missing

## Release record v1.0.0

Released 2026-09-19 from commit `7a13a5e` on `main`. Release:
https://github.com/acamarata/findplus/releases/tag/v1.0.0

| Asset | sha256 | Size |
|---|---|---|
| FindPlus-1.0.0-aarch64.dmg | `11b861c0ece6f5a7e13aee90f862e6569002e32de27616b98f7fcd341b733648` | 49 MB |
| FindPlus-1.0.0-aarch64.dmg.sha256 | `78f4a335a33d80d95f083b9cf80d3308c41ff8e20b0f018c45a1ebeba232e6c1` | 93 B |
| findplus-1.0.0-py3-none-any.whl | `c6fe30fc47a854ffe56136f329b5ce32050f4b137dfeafda2b35b031d077d85c` | 420 KB |
| findplus-1.0.0.tar.gz | `e5602874d2ed2389b1d1735786ff9328d17a0317cc2177a9b285b102f8e0d0c5` | 430 KB |
| install.sh | `f76bdc3b03ecad58bf1e6bd29a65df0d71ec84ee7201872f3dff401226436d04` | 4.5 KB |
| LICENSE | `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` | GPL-3.0 |
| CHANGELOG.md | `c8038dea27ab15f196f98420c9626241db1490fd2dd82890483ca1631b04ea8e` | |

Signing and notarisation, identity `Developer ID Application: Aric Camarata (5398R82926)`:
both `Find+.app` and the dmg were notarised and stapled, and `spctl -a -vv --type exec`
reports `accepted, source=Notarized Developer ID` for each. `codesign --verify --deep --strict`
exits 0, `hdiutil verify` exits 0, `verify-dmg.sh` passes at 49 MB against the 120 MB budget.
The sidecar launcher in `Contents/MacOS` is still the shell script; the notary service accepted
it, so the compiled-stub fallback was not needed.

PyPI outcome: deferred. `PYPI_API_TOKEN` is absent from `~/.claude/vault.env`, so nothing was
uploaded and `findplus` is not on PyPI.

Homebrew: the formula in `acamarata/homebrew-tap` is sourced from the GitHub Release, not PyPI,
because PyPI publish was deferred. Its url is
`https://github.com/acamarata/findplus/releases/download/v1.0.0/findplus-1.0.0.tar.gz` with
sha256 `e5602874d2ed2389b1d1735786ff9328d17a0317cc2177a9b285b102f8e0d0c5`. Tap commit
`041f0d265f53a6fd2c144eea6076bf0f8841fb72`. `brew install acamarata/tap/findplus` succeeds and
`$(brew --prefix)/bin/findplus --version` prints `findplus, version 1.0.0`.

`release.yml` on the tag (run 35476262190) finished with `build-python` and `github-release`
green, `build-dmg` and `publish-pypi` failed and `update-tap` skipped. That is the expected
state: the repo has no Apple signing secrets and no PyPI trusted-publishing environment. The
release itself was built, signed and uploaded from this machine, so those jobs are recorded here
rather than acted on.

Update 2026-09-20: `release.yml`'s `build-dmg` job was repaired after the tag run (commits
`d20430d`, `6a163a0`: install `tauri-cli`, unset the empty signing identity, allow a
`workflow_dispatch` dry run that never creates a release). Dispatch run 35477689893 built the
unsigned dmg on a clean runner. `publish-pypi` still needs the PyPI trusted publisher (owner item 2).

Owner items after this release:

1. Run `findplus auth` against your real Google account. Nothing in the build could do it.
2. Configure PyPI trusted publishing for `release.yml`, or add `PYPI_API_TOKEN` and upload
   `dist/findplus-1.0.0-py3-none-any.whl` and `dist/findplus-1.0.0.tar.gz` by hand.
3. The Intel dmg stays a conditional artefact (E13-T10). arm64 is the only build.
4. Walk the six GUI steps in `.github/docs/REHEARSAL.md`.
5. Dependabot PRs 1 to 5 are still parked. Set `if-no-files-found: warn` on `release.yml`'s
   finalise step before merging the `actions/upload-artifact` bump.
