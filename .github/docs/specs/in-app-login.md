# In-app login (design spec, Find+ 1.2.0)

Status: design, not built. Base `release/1.1.5` at `0961394`. Written 2026-10-01.
Tags: [Certain] = read in this repo or in the pinned crate source; [Likely] = strong inference;
[Guessing] = must be verified, usually by the owner with a real account (§9.4).

## 0. The ask, and the short answer

Owner: "improve the setup wizard and login flow (and any time we might lose auth also): if possible use a
web view inside the app or a window it controls, do the login, it auto grabs that oauth cookie and then
closes the window and the wizard just says Success ... Users can also set up both Google and Apple ...
When this is done we bump a minor version and release v1.2."

Short answer:
- **Google: yes, technically.** Tauri 2.11.6 (pinned) can open a window Find+ controls, give it a throwaway
  cookie store, read the HttpOnly `oauth_token` cookie from Rust, and close it (§2). The same window can then
  run the unlock page and catch the vault keys without touching vendored code (§4).
- **The weak point is Google, not Tauri.** Google has blocked sign-in from embedded browsers since 2019 and
  WKWebView is named in its policy. Whether `EmbeddedSetup` (the page Android's own add-account WebView uses)
  is exempt is unknown. Nobody has published evidence either way that I could find. **This must be proven
  with one real sign-in before any build work starts** (§8, package 0). If Google blocks it, the window shows
  that and the card falls back to the helper on its own (§3.3).
- **Apple: no web view.** FindMy.py signs in with SRP plus anisette, not with web cookies. A web page at
  appleid.apple.com would give the wrong kind of session (§5). Apple keeps the in-app form, redesigned into the
  same one-button card with a sheet.
- **Lost auth** gets one path for both providers: the tray turns to attention, one native banner, a tray item
  and a dashboard banner that open the same login (§6).
- **Pushback:** "auto grabs the cookie and the wizard just says Success" holds only for accounts with no
  passkey-only or Workspace SSO sign-in, and only while Google allows it. Plan for the fallback to be used.

## 1. What exists today (1.1.5)

| Piece | Where | Fact |
|---|---|---|
| Tauri shell | `desktop/src-tauri` | tauri 2.11.6, tauri-runtime-wry 2.11.4, wry 0.55.1, cookie 0.18.2, tauri-plugin-notification 2.4.0 in Cargo.lock [Certain] |
| Windows | `windows.rs` | `main` (remote `http://127.0.0.1:8647/`, init script sets `window.__findplus_native`) and `splash` [Certain] |
| Capabilities | `capabilities/{default,remote}.json` | `remote.json` grants `core:default` to window `main` for `http://127.0.0.1:8647/*` only [Certain] |
| Deep links | `urlscheme.rs` | five fixed `findplus://` URLs, pure `classify()` with tests [Certain] |
| Tray status | `status.rs` | `last_error_type == "auth"` gives "Sign-in needed" (red dot) [Certain] |
| Google token | `token_signin.py` | `sign_in_with_oauth_token(email, token, require_email=False)` runs gpsoauth's exchange, never logs the token [Certain] |
| Single-use state | `helper_state.py` | 256-bit `state`, 10 min TTL, `begin_exchange`/`end_exchange` retry semantics, `record_outcome` [Certain] |
| Helper flow | `browser-helper/`, `_routes_auth_google_helper.py` | user's Chrome plus extension; ingest needs pinned extension origin and state [Certain] |
| Unlock | `unlock.py`, `unlock_flow.py` | Find+'s own Chrome (undetected_chromedriver) opens `accounts.google.com`, waits for `myaccount.google.com`, loads `get_security_domain_request_url()`, injects `window.mm`, catches `setVaultSharedKeys` via `alert()` [Certain] |
| Unlock URL | vendored `KeyBackup/shared_key_request.py` | protobuf-built `https://accounts.google.com/encryption/unlock/android?kdi=...`; needs Python [Certain] |
| Key store | `unlock.store_vault_keys()` | parses vault JSON with vendored `get_fmdn_shared_key`, stores 0600, tags account [Certain] |
| Revoked | `revoked.py` | dead-login gpsoauth codes set `auth_revoked`; `finish_sign_in` clears it [Certain] |
| Apple | `apple_findmy/web_auth.py` | job: `signing_in -> needs_2fa -> done/failed`, SMS and trusted-device text, password never stored [Certain] |
| Wizard | `web/app/setup_steps/signin.js` | mounts the shared `signin/panel.js` cards; same cards as Settings [Certain] |

## 2. Google in-app window: the APIs, checked against the pinned crates

All of these exist in `tauri-2.11.6/src/webview/webview_window.rs` [Certain, read in the cargo registry]:

| Need | API | Platform notes (from the crate docs and wry 0.55.1 source) |
|---|---|---|
| Throwaway store | `WebviewWindowBuilder::incognito(true)` | macOS: wry picks `WKWebsiteDataStore::nonPersistentDataStore` when incognito is set, before any `data_store_identifier` (`wry/src/wkwebview/mod.rs:235`) [Certain]. Each call makes a new store, so Safari, Chrome and other apps are untouched [Likely]. Windows: WebView2 InPrivate, needs runtime 101+ [Certain]. Linux: `WebContext::new_ephemeral()` [Certain]. |
| Read HttpOnly cookies | `WebviewWindow::cookies()` / `cookies_for_url(Url)` | "including HTTP-only and secure cookies" [Certain]. macOS uses `WKHTTPCookieStore.getAllCookies` and spins the main run loop for at most 1 s (`wait_for_blocking_operation`) [Certain]. Windows deadlocks if called from a sync command or event handler; call from a worker thread [Certain, crate doc]. |
| Match the cookie | our own filter over `cookies()` | wry's macOS `cookies_for_url` keeps only cookies whose domain equals the URL host exactly, so a `.google.com` cookie would be missed [Certain]. Filter ourselves: name `oauth_token`, value starts `oauth2_4/`, domain ends `google.com` [Likely about the domain]. |
| Know when to look | `on_page_load` (Finished), `on_navigation`, plus a 500 ms poll | Poll on a dedicated thread; stop at success, close, cancel or 10 min [Certain the hooks exist]. |
| Navigation allow-list | `on_navigation(Fn(&Url) -> bool)` | returning false cancels before any request [Likely]. |
| No popups | `on_new_window(... -> NewWindowResponse::Deny)` | [Certain the hook exists]. |
| Bridge for unlock | `initialization_script(...)` | runs at document start on every main-frame load, including remote pages on macOS [Likely]. |
| Wipe | `clear_all_browsing_data()` then `close()` | [Certain the API exists]. |
| User agent | `user_agent(&str)` | exists; **not used**, see §3.2. |

Minimum OS: the app says macOS 13 (`tauri.conf.json`) [Certain]; `nonPersistentDataStore` and `getAllCookies`
are older than that [Likely]. `data_store_identifier` (macOS 14+) is not needed.

### 2.1 Flow

```
dashboard card / tray / deep link
  -> Rust: POST /api/auth/google/native/begin  (Origin http://127.0.0.1:8647)  -> {state, unlock_url}
  -> Rust: open window "signin-google", incognito, https://accounts.google.com/EmbeddedSetup
  -> Rust posts event "waiting" (card: "Finish signing in in the Find+ window")
  -> user signs in (password, 2-step) on Google's page
  -> poll thread sees oauth_token -> POST /api/auth/google/native/token {state, oauth_token}
  -> daemon: sign_in_with_oauth_token(require_email=False) -> account; needs shared_key?
       no  -> Rust shows "Signed in" in the window title for 1 s, wipes, closes
       yes -> Rust navigates the SAME window to unlock_url (already signed in there)
              -> page calls window.mm.setVaultSharedKeys -> bridge (§4) -> POST .../native/unlock
              -> daemon store_vault_keys() -> Rust wipes and closes the window
  -> card: "Connected as you@gmail.com. Locations unlocked."  (focus moves to that heading)
```

The page JavaScript never sees `state`, and the dashboard never sees the token or the keys. Rust holds
`state` and the token in memory only, for the length of one POST.

### 2.2 Daemon routes (new file `api/_routes_auth_google_native.py`)

| Route | Guard | Body / result |
|---|---|---|
| `POST /api/auth/google/native/begin` | `_require_origin_signal` + loopback Origin | `{mode: "signin"\|"unlock"}` -> `{state, unlock_url}`. `unlock_url` comes from vendored `get_security_domain_request_url()` (imported, not edited). |
| `POST /api/auth/google/native/token` | state (`begin_exchange` kind `native_signin`), Origin absent or loopback | `{state, oauth_token}` -> `{account, needs_unlock}`; errors are `token_signin` messages, never the token |
| `POST /api/auth/google/native/unlock` | state (kind `native_unlock`) | `{state, vault_keys}` -> `{state: "done"}` via `store_vault_keys()` |
| `POST /api/auth/google/native/event` | state | `{state, event: opened\|waiting\|blocked\|closed\|failed, reason?}`; feeds the card |
| `GET /api/auth/google/native/progress` | read-only | `{phase, message, account?, generation}` for the dashboard card |

The `state` is the credential for the three ingest routes. A cross-site browser POST carries a foreign
Origin and is refused by `OriginGuardMiddleware` already [Certain]. A local process could mint a state, but a
local process running as the user can already read `~/.findplus` [Certain]. One state covers the sign-in and
the unlock that follows it; it burns on the last successful step.

## 3. Google's policy, the ToS, and the fallback ladder

### 3.1 What is known

- April 2019: Google said it would block sign-in from embedded browser frameworks, because it "can't
  differentiate between a legitimate sign in and a MITM attack" there
  ([Google Security Blog, 2019-04-18](https://security.googleblog.com/2019/04/better-protection-against-man-in-middle.html)).
  The visible result is "Couldn't sign you in. This browser or app may not be secure." It has been reported for
  WebView2 ([WebView2Feedback #1584, 2021-07-29](https://github.com/MicrosoftEdge/WebView2Feedback/issues/1584))
  and for Electron-style apps ([ferdium #1179](https://github.com/ferdium/ferdium-app/issues/1179)).
- Sept 2021: the OAuth 2.0 authorization endpoint returns `disallowed_useragent` for embedded webviews, naming
  WKWebView ([Google Developers Blog](https://developers.googleblog.com/upcoming-security-changes-to-googles-oauth-20-authorization-endpoint-in-embedded-webviews/);
  [Auth0 summary](https://auth0.com/blog/google-blocks-oauth-requests-from-embedded-browsers/)).
  **Find+ never calls that endpoint.** `EmbeddedSetup` is account sign-in for Android device setup, not an
  OAuth client flow [Likely]. So the 2019 sign-in block is the rule that matters, not the 2021 one.
- FOSS practice: gpsoauth users, GoogleFindMyTools and the Home Assistant integrations all get `oauth_token` from
  a **real browser** (DevTools or Chrome driven by Selenium), never from a webview
  ([julianpitt master-token gist](https://gist.github.com/julianpitt/94774e74d36a46f9ec10ddce13cfd423);
  [gpsoauth-java README](https://github.com/rukins/gpsoauth-java/blob/b74ebca999d0f5bd38a2eafe3c0d50be552f6385/README.md);
  [GoogleFindMy-HA](https://github.com/BSkando/GoogleFindMy-HA)). Comments on the gist from March to May 2026
  report it still works, and one reports a "suspicious activity" warning five days later. I found **no**
  report of `EmbeddedSetup` in WKWebView, working or failing. That gap is the reason for package 0.
- GoogleFindMy-HA warns that Google may revoke keys used from a different IP or region. Find+ signs in and
  polls from the same Mac, so this helps us [Likely].

### 3.2 User agent policy

Keep WKWebView's default UA. **Never spoof Chrome or Safari.** Reasons: it is deception aimed at Google's
security check, posts and blogs call it a ToS problem ([cnr.sh essay](https://cnr.sh/essays/google-oauth-wkwebview)),
it reportedly does not help reliably, and an account flagged for it is the owner's real account. If the honest
UA is blocked, the answer is the fallback, not a disguise. Owner question Q1.

### 3.3 ToS, plainly

Find+ already relies on interfaces Google does not publish (gpsoauth, Nova, the unlock page). That is the
larger ToS exposure and it is not new in 1.2. Google's current terms (effective 2026-07-30) forbid automated
access that ignores machine-readable rules ([policies.google.com/terms](https://policies.google.com/terms)).
A person signing in by hand in a window is not that. But an embedded sign-in goes against Google's stated
security policy, and Google can block it at any time without notice. The wiki must say so in one sentence.

### 3.4 Detecting a blocked window, then falling back

Signals, in order of trust:
1. Navigation to a rejection page: path matching `/signin/rejected` or `/v3/signin/rejected`, or
   `disallowed_useragent` anywhere in the URL [Guessing the exact paths; package 0 records them].
2. No `oauth_token` and no navigation for 3 minutes after the last page load (stuck).
3. The user closes the window (Cmd+W): not a block, a cancel.

Blocked means: Rust posts `event: blocked`, wipes and closes the window, and the card says:
"Google would not let Find+ sign you in inside the app. Use your Chrome instead." with the helper button
first. Find+ remembers `native_blocked_at` for 7 days and starts at the helper during that time, with a quiet
"Try the Find+ window again" link.

Ladder (each step is a button the user presses; nothing opens Chrome on its own):
1. Find+ sign-in window (desktop app only, default).
2. Chrome helper (existing, in the user's own Chrome).
3. Paste the cookie (existing).
4. Find+'s own Chrome window (existing, undetected_chromedriver). Demoted in 1.2 and hidden under
   "More ways"; candidate for removal in 1.3 (owner question Q4).

## 4. Unlock in the same window

The unlock page expects an Android-style JavaScript interface `window.mm` with `setVaultSharedKeys(str,
vaultKeys)` and `closeView()` [Certain, from vendored `shared_key_flow.py` and our `unlock_flow._BRIDGE`].

What must be reproduced (vendored code stays untouched; rule 8):
- the URL: daemon calls `get_security_domain_request_url()` and hands it to Rust in `begin` [Certain it is importable];
- a signed-in session in the window: after EmbeddedSetup it is the same cookie store [Guessing that the
  EmbeddedSetup session is enough for `/encryption/unlock`; package 0 checks]; for unlock-only (key reset,
  re-unlock) load `https://accounts.google.com/` first and wait for `myaccount.google.com`, as the vendored flow does;
- `window.mm` defined before the page needs it;
- parsing: `store_vault_keys()` already wraps `get_fmdn_shared_key` [Certain].

Bridge design: **no Tauri IPC.** The init script runs only when `location.origin` is
`https://accounts.google.com` and the path starts `/encryption/unlock/`. Its `setVaultSharedKeys` navigates to
`https://findplus-bridge.invalid/vault#<base64url(JSON)>`, and `closeView` to `.../close`. The
`on_navigation` handler catches the `.invalid` host, decodes the fragment, returns false (no request ever
leaves), and posts the keys to the daemon. This keeps every Tauri command out of reach of Google's page. The
same trick reports the signed-in email from `myaccount.google.com` for the account-mismatch check that
`unlock_flow._check_account` does today.

Risk: a script on accounts.google.com could navigate to the bridge with junk. Worst case is a bad key, which
`store_vault_keys` rejects or the next poll fails to decrypt. Google's page is the party we trust for the key
anyway [Likely acceptable].

## 5. Apple

Why no web view [Likely]: FindMy.py logs in with Apple's GSA SRP protocol plus anisette headers that make the
request look like a provisioned Apple device ([FindMy on PyPI, 0.9.8, 2026-01-08](https://pypi.org/project/FindMy/)).
A web login at appleid.apple.com or icloud.com sets web cookies for iCloud web, which FindMy.py cannot use to
fetch encrypted location reports. Apple's page in a webview would add a second sign-in for no gain.

Redesign, same card shape as Google:
- One **Connect** button opens an in-dashboard sheet (focus trapped, Escape closes): Apple ID, password, Connect.
- First run on a Mac without anisette libs: "Preparing Apple sign-in (one-time download, a few MB)" step,
  because `prepare_anisette` downloads `anisette-libs.bin` [Certain the file exists in `auth.py`].
- 2FA: default trusted device ("Enter the 6-digit code shown on your iPhone, iPad or Mac"); a "Text me
  instead" link lists the masked numbers FindMy.py returns; the existing `MSG_NEEDS_SMS` names the number.
- Success: sheet closes, card says "Connected as name@icloud.com", focus to that heading.
- The password lives only in the sign-in thread, as today [Certain].

## 6. Lost auth (both providers)

Detection [Certain the inputs exist]: Google `auth_revoked` or `last_error_type == "auth"`; Google
`needs: shared_key` after a key reset; Apple `AppleAuthRequiredError`. New: `/api/auth/status` gains
`attention: "signin" | "unlock" | null` per provider so Rust and the web read one field.

Surfaces:
1. **Tray:** the dot turns attention (existing red "Sign-in needed"), plus a top menu item
   "Sign in to Google again..." or "Unlock Google locations..." or "Sign in to Apple again..." that opens the
   login directly (Google window; Apple: dashboard with the sheet open).
2. **One native banner per loss**, from Rust on the transition into attention, deduped until the provider is
   healthy again: title "Find+ needs you", body "Google signed Find+ out. Click the Find+ menu bar icon to
   sign in again." No account and no place in it, which also satisfies the generic-while-locked rule in `notify.rs`.
   tauri-plugin-notification 2.4.0 has no click callback on desktop [Certain: `desktop.rs` exposes only
   builder/show/permission], so the banner text points to the tray. If macOS delivers `RunEvent::Reopen`
   when the banner is clicked, open the login then [Guessing].
3. **Dashboard banner** (existing `poll_status.js` "signin"/"unlock" actions): in the app it calls the same
   Tauri command; in a browser tab it scrolls to the card as today.
4. **Deep links:** `findplus://signin/google`, `findplus://unlock/google`, `findplus://signin/apple`. A web page
   can fire these, so they open the login window **only while that provider has `attention` set**; otherwise
   they open Settings > Sign-in. Add them to `classify()` with tests.

## 7. Wizard and Settings UX

One card per provider, in both the wizard step and Settings (they already share `signin/panel.js`).

| Card state | Shows | Primary action |
|---|---|---|
| not connected | provider name, one line on what it adds | **Connect** |
| connecting | spinner "Opening the sign-in window..." | Cancel |
| waiting for you | "Finish signing in in the Find+ window." | Show window, Cancel |
| finishing | "Checking with Google..." | none |
| needs unlock | "One more step: enter your Android phone's screen lock in the same window." | (window stays open) |
| success | check icon, "Connected as x@y", "Locations unlocked" | Disconnect (secondary) |
| blocked-embedded | §3.4 text | **Use your Chrome** (helper), More ways |
| error | plain cause + Retry | Retry, More ways |

Copy rules: no jargon ("cookie", "token" never shown on the main path), no em dashes, honesty sentences
unchanged and test-pinned. New strings go through `web/locales/en.json` and `gen-honesty-json.py`.

Wizard: step "Connect your accounts" shows both cards side by side (stacked under 768 px). Next is enabled
once at least one provider is connected, Skip as today. "Success" is the card's own state, not a page.

Accessibility: the login window is third-party content. Window title "Find+ sign-in: Google
(accounts.google.com)", the host updated on each page load so a person can see where they are typing. When
it opens, the card's live region says "A Find+ sign-in window opened." On close, Rust focuses `main` and the
card moves focus to its result heading (`tabindex=-1`). Every state change is announced once, politely.
Cmd+W in the login window means Cancel.

Browser-only mode (no `window.__findplus_native`): the card hides the window option and leads with the helper
flow, exactly as 1.1.5. Windows and Linux: the desktop shell ships for macOS only today (`bundle.targets` is
app and dmg) [Certain]; the Rust code stays cross-platform but is untested there, so those users get
browser-only mode.

## 8. Work packages and order

| # | Package | Owns | Depends on |
|---|---|---|---|
| 0 | **Spike, owner-run (gate).** Debug build with a bare window: EmbeddedSetup, incognito, log host+path of each navigation and whether `oauth_token` appeared (never the value); then the unlock URL with the bridge. 15 min with a real account. | throwaway branch, nothing merged | none |
| A | Rust: `signin_window.rs` (open, poll, bridge, wipe), `signin_logic.rs` (pure: allow-list, blocked classifier, cookie pick, URL redaction, bridge decode, state machine), command `open_signin_window`, tray item, attention banner, deep links, `remote.json` permission for `main` only | `desktop/src-tauri/**` | 0, and B's route contract (§2.2) |
| B | Daemon: `_routes_auth_google_native.py`, `native_state` kinds in `helper_state.py`, `attention` in `/api/auth/status`, unlock URL, tests | `cli/src/findplus/api/_routes_auth_google_native.py`, `providers/google_findhub/native_flow.py`, `helper_state.py`, tests | contract only |
| C | Web: `signin/google_native_flow.js`, card states, Apple sheet, banner wiring, en.json, Playwright | `web/app/signin/**`, `web/app/setup_steps/signin.js`, `web/locales/en.json`, `cli/tests/ui/**` | B (stubbable) |
| D | Docs and release: wiki `Sign-in.md`, CHANGELOG 1.2.0, README, uninstall notes | `.github/wiki/**`, `CHANGELOG.md` | A, B, C green |

A and B run in parallel; C starts against a stubbed bridge; D last. Every file stays under 300 lines.

### 8.1 Package 0 status

Not yet run with a real account: owner UAT steps list in Desktop-manual-tests.md. A, B, C and D
were built and tested against fakes only (fake EmbeddedSetup, unlock and daemon on 127.0.0.1, a
stub bridge in the dashboard). Everything marked [Guessing] in §3 and §4 (the rejection paths,
whether the EmbeddedSetup session is enough for `/encryption/unlock`, which frames Google's pages
load) is still a guess until the owner runs [Desktop manual tests](../../wiki/Desktop-manual-tests.md),
section "In-app sign-in (1.2.0)", and the results are written here.

## 9. Security review and tests

### 9.1 Window hardening
- Label `signin-google`; **no capability lists it** (`default.json`: main, splash; `remote.json`: main) so any
  `invoke` from Google's page is refused by Tauri's ACL for non-local origins
  (`tauri-2.11.6/src/webview/mod.rs` ~1820: remote origins are checked against capabilities) [Certain the gate exists;
  Likely it rejects with no match]. `withGlobalTauri: true` still injects `window.__TAURI__` everywhere [Likely]: harmless
  without a grant, but a unit test asserts both JSON files never name the sign-in label or a Google URL.
- Allow-list: https only; hosts `accounts.google.com`, `accounts.google.<cc>` and `accounts.youtube.com`
  (cross-domain sign-in cookies), `myaccount.google.com`, `www.google.com`, `ssl.gstatic.com`; the `.invalid`
  bridge host is handled and cancelled. Everything else is cancelled and logged by host only. Workspace SSO
  to a third-party IdP is therefore refused, and the card offers the helper (Q3).
- `127.0.0.1` and `localhost` are never allowed in this window, so it can never load the dashboard.
- No popups, no devtools in release, clipboard off, no file downloads.
- Wipe on every exit path (success, cancel, block, error, app quit): `clear_all_browsing_data()`, then close.

### 9.2 Token and log handling
- Token and vault keys: Rust memory only, one POST each, then dropped. Never in events, window titles,
  emitted Tauri events, logs or the daemon store (`_SENSITIVE_KEYS` unchanged; vault keys become `shared_key` 0600 as today).
- Rust logs URLs through `redact_url()` (scheme, host, path; no query, no fragment). The bridge URL is never
  logged. Unit-tested.
- Daemon: the new bodies use the `Any`-typed field pattern from `_routes_auth_google_token.py`, so FastAPI
  never echoes a token in a 422 [Certain the pattern exists].

### 9.3 Automated tests (no real Google, no real Chrome, no network)
- Rust unit (`signin_logic_tests.rs`): allow-list table, blocked classifier, cookie picker (wrong name, wrong
  prefix, `.google.com` vs host-only, expired), bridge decode (bad base64, oversize over 64 KB, wrong host),
  redaction, state transitions, deep-link gating on `attention`, capability JSON assertion.
- Rust integration, debug builds only: `FINDPLUS_SIGNIN_TEST_BASE=http://127.0.0.1:<spare>` points the window
  at a fake EmbeddedSetup server that sets `oauth_token=oauth2_4/test` and serves a fake unlock page calling
  `window.mm.setVaultSharedKeys` with sample vault keys. The override is `#[cfg(debug_assertions)]` so a
  release build cannot be pointed elsewhere. Also try `set_cookie` injection to test the poller without a page.
- Daemon pytest: routes with gpsoauth monkeypatched, state reuse refused, foreign Origin 403, token never in
  responses or caplog, `attention` field per provider.
- Playwright (bundled Chromium, private state dir): wizard and Settings cards in every §7 state with a stubbed
  `window.__TAURI__.core.invoke` and stubbed progress route; browser-only mode; 375/768/1280; light/dark;
  keyboard and focus return; axe-style checks already in `cli/tests/ui`.

### 9.4 Owner-only UAT (real accounts; the only way to prove §3 and §4)
1. Fresh state dir, open app, wizard: Connect Google. Window title shows `accounts.google.com`.
2. Sign in with password and 2-step. Expect no "This browser or app may not be secure". Note the outcome.
3. Expect the unlock prompt in the same window; enter the Android screen lock. Window closes; card says Connected and unlocked.
4. Check `~/.findplus/secrets.json` has `aas_token` and `shared_key`; check app logs contain no `oauth2_4/` and no vault JSON (`grep`).
5. Check Safari and Chrome are still signed in exactly as before, and the window left no data
   (`~/Library/WebKit/com.acamarata.findplus` holds no new Google cookies).
6. Connect Apple in the same wizard: password, trusted-device code, then repeat with "Text me instead".
7. Revoke Find+'s access at myaccount.google.com (or change password). Wait one poll. Expect the tray attention,
   one banner, the tray item; click it; sign in; banner clears.
8. Cancel mid-sign-in with Cmd+W; expect "Cancelled" and no state change.
9. Repeat step 2 a week later to see if Google flags the account (the gist's 5-day report).

## 10. Release plan for 1.2.0

- Version: `cli/pyproject.toml` to `1.2.0` (tauri.conf follows via `build.rs` [Certain]) and the helper
  `manifest.json`. Version bumps and publishing stay owner-gated (PRI rule 10); the owner's request covers
  the bump, the publish still needs the explicit go.
- Migration: existing sessions are untouched; nobody is asked to sign in again. The helper and paste paths stay.
- CHANGELOG: "Sign in to Google in a Find+ window; Find+ closes it when you are done. Unlock happens in the
  same window. Apple sign-in in one sheet. Clear prompt when a sign-in stops working."
- Cleanup: the in-app window persists nothing. `~/.findplus/chrome-profile` (from the old own-Chrome path)
  stays until the user removes it; uninstall docs list it.
- Gates: the PRI list (pytest, ruff, node --check, shellcheck, clippy -D warnings, cargo test, widget build)
  plus package 0's result recorded in this file (§8.1: not yet run with a real account).
- Consent: before the window opens the card says, from `honesty.NATIVE_SIGNIN_KEPT`: "Find+ keeps a
  long-lived sign-in to your Google account on this Mac so it can read your trackers. You can remove
  its access any time at myaccount.google.com/security (Third-party access) or with Disconnect."

## 11. Adversarial critique

- **Google blocks it next month.** Likely at some point. The fallback is automatic (§3.4) and the helper path
  stays first-class, so the cost is one extra click, not a broken app. Do not build anything that only works
  in the window. Keep the helper extension maintained.
- **Google blocks it today.** Then package 0 fails and 1.2 shrinks to: better cards, lost-auth handling,
  Apple sheet, and the unlock-in-window (if the unlock page works where sign-in does not). Still worth a minor.
- **Cookies API is macOS-only?** No: wry implements cookies for WebKitGTK and WebView2 too [Certain]. But
  only macOS ships, so only macOS is tested.
- **Owner's real Chrome must never be touched.** The window is WKWebView with a non-persistent store: it
  does not launch Chrome, read Chrome's profile, or share Safari's cookies [Likely; UAT step 5 proves it].
  The helper fallback opens a tab in the user's Chrome only when they press that button. Tests use bundled
  Chromium only.
- **Passkeys and password managers.** WKWebView in a non-browser app likely cannot use iCloud Keychain
  autofill or platform passkeys [Likely]. People with passkey-only accounts will need "Try another way" or the
  helper. This makes the window worse than Chrome for some users; the card must say "Prefer your Chrome?" on
  the waiting state.
- **Phishing optics.** An app window asking for a Google password is exactly what Google's policy fights. The
  host in the title helps but is not an address bar. Honest framing in the wiki; never pre-fill or read fields.
- **Embedded detection may change silently** (works for some accounts, not others). The 7-day memory of a
  block and the always-visible fallback keep that from trapping anyone.

## 12. Questions for the owner (defaults apply if unanswered)

1. UA: never spoof, fall back instead? **Default: never spoof.**
2. Run package 0 yourself before any build work (15 minutes, your real account)? **Default: yes, build waits for it.**
3. Workspace accounts with outside SSO: refuse in the window and offer the helper? **Default: yes.**
4. Hide the old "Find+ opens its own Chrome window" path in 1.2 and remove it in 1.3? **Default: hide in 1.2, remove in 1.3.**
5. One native banner per sign-in loss, no repeats? **Default: one, plus the tray item until fixed.**
6. Publish 1.2.0 after UAT passes: you press publish, as for 1.1.x? **Default: yes, owner publishes.**
