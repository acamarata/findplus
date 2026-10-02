# Find+.app — build notes

Tauri 2 shell over the existing daemon dashboard. No JavaScript build step; the app
loads `http://127.0.0.1:8647/` once the bundled Python daemon answers a health probe.
Full architecture: `../.claude/phases/current/p1/specs/desktop-app.md`.

## Prerequisites

- Rust stable (`rustup show`)
- `cargo install tauri-cli --version "^2.11"` (or a workspace-pinned `cargo-tauri`)
- Python 3.12 with `pip install ".[bundle]"` (from `cli/`) for `pyinstaller>=6.22`
- Xcode 15+ (for the WidgetKit extension)
- `APPLE_SIGNING_IDENTITY` in the environment for signed builds (Developer ID
  Application identity in the keychain)

## Supported architectures

- Apple Silicon (arm64) — macOS 13 or later
- Intel (x86_64) — macOS 13 or later

Local builds produce arm64 only. Pass `--target x86_64-apple-darwin` to
`cargo tauri build` and use `packaging/pyinstaller/findplus-daemon-x86_64.spec` for the
sidecar to produce an Intel binary locally.

## Build order

1. PyInstaller sidecar
2. `sign-sidecar.sh`
3. Widget `xcodebuild`
4. `cargo tauri build`
5. `embed-widget.sh`

## Sidecar

```
pyinstaller packaging/pyinstaller/findplus-daemon.spec
```

Copies the PyInstaller onedir to `desktop/src-tauri/resources/findplus-daemon/`, which
Tauri ships inside `Find+.app/Contents/Resources/`. The `externalBin` entry
`binaries/findplus-daemon-<triple>` is a committed launcher script that execs the
binary in there, because `externalBin` takes one file and the daemon is a directory.

## Signing

Run `packaging/scripts/sign-sidecar.sh` before `cargo tauri build`. Set
`APPLE_SIGNING_IDENTITY`, and `APPLE_API_KEY_P8_BASE64`, `APPLE_API_KEY_ID`,
`APPLE_API_ISSUER_ID` for notarisation.

## Local unsigned build

```
cargo tauri build --target aarch64-apple-darwin
```

Unsigned builds are opened with right-click → Open (Gatekeeper).

## Widget

```
xcodebuild -project desktop/widget/FindPlusWidget.xcodeproj -scheme FindPlusWidget \
  -configuration Release -arch arm64 build
```

Embed via `packaging/scripts/embed-widget.sh`.

## In-app sign-in window (1.2)

`src/signin_*.rs` open Google's sign-in in a window Find+ controls (spec:
`.github/docs/specs/in-app-login.md`). The window uses a throwaway cookie store,
has no Tauri capability, and only loads Google sign-in hosts over https.
`src/attention.rs` drives the tray's "Sign in again" item and the one banner per
lost sign-in.

Debug builds can drive the real window against a local fake site (no Google,
no Chrome; a small window opens for a few seconds per case):

```
cd desktop/src-tauri
FINDPLUS_SIGNIN_E2E=1 cargo test --test signin_e2e
FINDPLUS_SIGNIN_SELFTEST=ok cargo run     # also: unlock, reject, cancel
```

Release builds contain no fake site and cannot be pointed away from Google.
The older owner-run probe stays behind the `login-probe` feature (`PROBE.md`).

## DMG size budget

≤ 120 MB.
