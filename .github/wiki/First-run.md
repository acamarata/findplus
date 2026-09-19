# First run

Two commands:

```bash
findplus auth
findplus start
```

`findplus auth` opens Chrome to sign in with your Google account (or runs an
interactive Apple sign-in with `--provider apple-find-my`). `findplus start`
installs a user-level service, begins polling, and opens the dashboard at
http://localhost:8647 in your browser automatically.

![Dashboard](.github/docs/screenshots/dashboard-light.png)

From the dashboard, open **Devices** to choose which trackers to follow, or
run `findplus devices --track-all` from the CLI. Add a place from the map
with the crosshair tool, and set up alerts from the Alerts tab.

If the browser does not open on its own, run `findplus open`.

---
[[Home]]
