# Fresh-machine rehearsal, pre-release

Run on 2026-09-19 by the P1-E15-W9-S1-T4 builder with
`packaging/scripts/rehearse-fresh-machine.sh all`. The script installs Find+ the way a new
user would, on two machines that hold nothing but Python, then reinstalls over itself and
uninstalls. It never escalates privileges, never creates a user account, and never reads or
writes the real `~/.findplus` or port 8647.

## Environments

| Leg | Machine | Python | Isolation |
|---|---|---|---|
| macOS | Darwin 27, arm64 | python3.13 (3.13.12), found first on the clean PATH | `env -i` plus a throwaway HOME under `/tmp/fp-rehearsal.XXXXXX`, removed by an EXIT trap |
| Linux | `docker run --rm python:3.12`, arm64 | python3.12 (3.12.14), chosen after python3.13 was rejected | container filesystem, HOME at `/tmp/fp-home`, repo mounted read only at `/src` |

Both legs serve on port 18647, so a daemon on 8647 is never disturbed.

## macOS leg

```
bash packaging/scripts/rehearse-fresh-machine.sh macos
```

```
== wheel: dist/findplus-1.0.0.dev0-py3-none-any.whl
== fresh install
  Python:  python3.13 (Python 3.13.12)
  Venv:    /tmp/fp-rehearsal.AWXPRv/home/.local/share/findplus/venv
  Symlink: /tmp/fp-rehearsal.AWXPRv/home/.local/bin/findplus
  Package: dist/findplus-1.0.0.dev0-py3-none-any.whl
findplus, version 1.0.0.dev0
== doctor
== auth --help
== serve and probe
{"status":"ok","app":"findplus","version":"1.0.0.dev0", ...}
== state isolation
== idempotent reinstall
Existing venv found, running pip install --upgrade
== uninstall
State directory /tmp/fp-rehearsal.AWXPRv/home/.findplus left intact.
REHEARSAL-MACOS-PASS
```

`doctor` exits 1 on a machine with no state, no sign-in and no service. That is the correct
report, not a failure, so the script records the output and keeps going. The line it asserts
on is `Provider authentication: apple-find-my: not configured ...; google-find-hub: not
signed-in`.

## Linux leg

```
bash packaging/scripts/rehearse-fresh-machine.sh linux
```

```
== wheel: /src/dist/findplus-1.0.0.dev0-py3-none-any.whl
== fresh install
  Python:  python3.12 (Python 3.12.14)
  Venv:    /tmp/fp-home/.local/share/findplus/venv
  Symlink: /tmp/fp-home/.local/bin/findplus
  Package: /src/dist/findplus-1.0.0.dev0-py3-none-any.whl
findplus, version 1.0.0.dev0
== doctor
== auth --help
== serve and probe
{"status":"ok","app":"findplus","version":"1.0.0.dev0", ...}
== state isolation
== idempotent reinstall
Existing venv found, running pip install --upgrade
== uninstall
State directory /tmp/fp-home/.findplus left intact.
REHEARSAL-LINUX-PASS
```

A missing Chrome on Linux is recorded output, never a failure.

## Defects found and fixes

| File | Symptom | Fix |
|---|---|---|
| `install.sh` | the Debian image has a python3.13 without the venv module, and install.sh picked it first, so the install died at `python3.13 -m venv` with a message telling the user to run apt | `find_python` now also requires `import venv, ensurepip` and falls through to the next candidate |
| `install.sh` | `--uninstall` left an empty `~/.local/share/findplus` behind | the uninstall path `rmdir`s the prefix when it is empty |
| `install.sh` | a second install printed exactly what the first did, so nothing showed the upgrade path had been taken | the existing-venv branch prints `Existing venv found, running pip install --upgrade` |
| `cli/src/findplus/service/watchdog.py` | `findplus uninstall --yes` raised `FileNotFoundError: 'systemctl'` inside the container, which install.sh then reported as a service uninstall error | the three watchdog calls go through `service/_proc.run`, which checks the binary first |
| `packaging/scripts/rehearse-fresh-machine.sh` | the doctor assertion in the ticket text was `not signed in`; the implemented wording is `not signed-in` | the script asserts the implemented line |

Each fix was made inside this ticket and both legs were re-run green afterwards.

## Idempotency

The second install runs against the venv the first one created:

```
  Venv:    /tmp/fp-home/.local/share/findplus/venv
Existing venv found, running pip install --upgrade
Installed. Run: findplus auth
```

The uninstall then removes the venv and the symlink and says which state directory it left
alone, and the script asserts that the directory is still there:

```
Removing /tmp/fp-home/.local/share/findplus/venv and /tmp/fp-home/.local/bin/findplus
State directory /tmp/fp-home/.findplus left intact.
```

## Owner post-handoff GUI checklist

The dmg and the app window need a real desktop session, so these six steps are yours to run
once. Nothing below is covered by the automated legs above.

1. Mount `dist/FindPlus-1.0.0-aarch64.dmg` and confirm Gatekeeper accepts the app on first launch.
2. Drag `Find+.app` to `/Applications` and open it from there.
3. Confirm the tray icon appears in the menu bar.
4. Choose `Open App` and confirm the dashboard loads at http://127.0.0.1:8647/.
5. Choose `Quit` and confirm the dialog offers to install the background service.
6. After quitting, run `pgrep -f findplus-daemon` and confirm at most the LaunchAgent daemon is left.

## Verdict

| Leg | Result |
|---|---|
| macOS | PASS, `REHEARSAL-MACOS-PASS`, exit 0 |
| Linux | PASS, `REHEARSAL-LINUX-PASS`, exit 0 |
