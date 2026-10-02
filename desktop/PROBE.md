# Google sign-in probe (package 0 gate)

A 15-minute test. It answers one question: does Google let a Find+ window sign you in, and can Find+ then
read the sign-in cookie? Nothing is saved, sent or kept. It is a developer build, not the app you install.

## Run it
1. Quit Find+ if it is running (the probe uses its own window, no daemon).
2. In a terminal:
   `cd desktop/src-tauri && cargo run --features login-probe -- --probe-google-embedded`
3. A window titled "Find+ sign-in probe (test window)" opens on Google's sign-in page.
4. Sign in with a throwaway Google account, or your real one. Do the 2-step prompt if asked.
5. You are done when the window closes by itself (a few seconds after the cookie appears) or when you
   close it yourself (red button). If Google shows an error page, just close the window.
6. A results box opens. Press "Copy report" and paste it back to the team. Press "Close" to quit.

## What the report says
Where you ended up (site and path only), whether Google rejected the window, whether the sign-in cookie
appeared (YES or NO and its length, never the value), the browser string used, and how long it took.
It holds no passwords, no email address and no cookie value.

## Safety
- The window is private: it shares nothing with Safari, Chrome or Find+, and is wiped when it closes.
- It may only visit Google sign-in sites, and the page it shows cannot call into the app.
- It never starts Chrome. It is only built when you pass `--features login-probe`; release builds do not.

## Test it without Google (debug builds)
`FINDPLUS_PROBE_FAKE=ok cargo run --features login-probe -- --probe-google-embedded` opens a local fake page;
click its button and close the window. Use `reject` to see the rejected case, or `ok-auto` with
`FINDPLUS_PROBE_NO_DIALOG=1` for an unattended run that prints the report to the terminal.
