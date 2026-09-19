## What this PR does
<!-- One sentence -->

## Gate checklist
- [ ] `pytest cli/tests -q` green
- [ ] `ruff check cli/src cli/tests && ruff format --check cli/src cli/tests` clean
- [ ] `find web -name '*.js' | xargs node --check` clean
- [ ] `shellcheck install.sh` clean
- [ ] `cargo clippy --manifest-path desktop/src-tauri/Cargo.toml -- -D warnings` clean
- [ ] `cargo test --manifest-path desktop/src-tauri/Cargo.toml` green
- [ ] `xcodebuild -scheme FindPlusWidgetExtension build` clean
- [ ] No `Co-Authored-By` lines added
- [ ] CHANGELOG.md updated if user-visible change

## Screenshots (if UI change)
