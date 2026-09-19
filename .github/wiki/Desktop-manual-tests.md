# Desktop manual test checklist

These five edge cases (PLAN.md § E13-T8) need a real signed or locally-built
`Find+.app` and a real macOS session — they are not exercised by `cargo
test` (which covers the pure `decide()`/`from_api()` branching instead).

- [ ] CLI daemon on port 8647 → tray shows a "CLI daemon v&lt;old&gt;" warning
      (run `findplus start --yes` from an older checkout, then launch
      Find+.app and confirm the log line, `daemon: CLI daemon v...`).
- [ ] Kill daemon process → tray goes amber within 90 s; "Restart daemon"
      appears (kill the sidecar's pid from `~/.findplus/daemon.json`, wait
      for the next 45 s poll plus the 20 s re-probe window).
- [ ] Lock via tray Lock item → tray goes grey; Poll Now disabled.
- [ ] Remove Chrome → sign out and back in → tray shows "Sign in" item
      instead of "Open Dashboard" (rename `/Applications/Google Chrome.app`
      temporarily, then `findplus auth`; check `GET /api/providers` reports
      `google-find-hub` unavailable with a Chrome-mentioning reason).
- [ ] Quit with sidecar running → confirm dialog appears with the exact
      wording "Polling stops when Find+ quits. Install the background
      service so it keeps running?" and all three buttons act correctly.
