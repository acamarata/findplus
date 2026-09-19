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
cd /Volumes/UG/Sites/acamarata/findplus && pyinstaller packaging/pyinstaller/findplus-daemon.spec
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

## DMG size budget

≤ 120 MB.
