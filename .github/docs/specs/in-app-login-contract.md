# In-app login: daemon contract (Find+ 1.2.0)

What the daemon (package B) serves for the desktop shell (package A) and the dashboard card
(package C). Design: [in-app-login.md](in-app-login.md). Code:
`cli/src/findplus/api/_routes_auth_google_native.py`, `providers/google_findhub/native_flow.py`,
`native_progress.py`, `native_classify.py`, `native_messages.py`, `providers/attention.py`,
`providers/apple_findmy/signin_sheet.py`, `api/_routes_auth_apple_sheet.py`.

## 1. Conventions

- Base: `http://127.0.0.1:<port>` (8647 by default). JSON bodies, `Content-Type: application/json`.
- Every native refusal is `{"detail": "<plain words for a person>", "code": "<word>"}`. Show `detail`;
  branch on `code` and the HTTP status. `detail` never holds a token, a key or page contents.
- Body fields are typed loosely on purpose: a wrong type is answered in plain words, never with a
  422 that quotes the body back.
- The token and the vault keys go in exactly one POST each. The daemon never stores, logs or
  returns them (the account email is returned; it is an identifier).

## 2. Who may call what

| Route | Caller | Headers required | App lock |
|---|---|---|---|
| `POST /api/auth/google/native/begin` | shell or dashboard | `Origin: http://127.0.0.1:<port>` (any loopback Origin on the daemon's port passes the middleware; a missing Origin is 403) | 401 while locked |
| `POST /api/auth/google/native/token` | shell only | `Origin: http://127.0.0.1:<port>` exactly AND `X-FindPlus-Client: signin-window` | exempt; own gate |
| `POST /api/auth/google/native/unlock` | shell only | same as token | exempt; own gate |
| `POST /api/auth/google/native/event` | shell only | same as token | exempt; own gate |
| `POST /api/auth/google/native/classify` | shell only | same as token | exempt; own gate |
| `GET  /api/auth/google/native/progress` | dashboard (shell when unlocked) | none | 401 while locked |
| `POST /api/auth/google/native/cancel` | dashboard or shell | `Origin` or `Sec-Fetch-Site` | 401 while locked |
| `GET  /api/auth/status` | everyone | none | 401 while locked |

Own gate = both shell headers AND a live single-use state of the right kind. Wrong headers: 403
`bad_client`. No such state: 403 `state_invalid`. A Chrome-helper state never works here, and a
native state never works on the helper routes.

Lock: a state can only be minted by an unlocked session, so the ingest routes stay usable for the
ten minutes a window may be open even if the app locks meanwhile. If the shell's own `begin` gets a
401, the app is locked: bring up `main` (its lock screen) and do not open the window. Recommended
path that works locked or not: the card calls `begin` (it has the session cookie) and passes the
whole response to the Tauri command `open_signin_window`. Tray and deep-link paths may call `begin`
from Rust and fall back to showing the card on 401.

## 3. Routes

### 3.1 begin

`POST /api/auth/google/native/begin` body `{"mode": "signin" | "unlock", "if_idle": true | false}`
(defaults `signin`, `false`). A new begin drops any older native state (one window at a time).
The card always sends `if_idle: true`: while a window is still working (a live phase, §3.8) the
daemon answers 409 `window_open` with `{"detail", "code", "flow", "mode"}` instead of replacing
it, and the card follows that window (it calls `open_signin_window` without a begin, which only
brings the window forward). The shell's own begin (tray, deep link) never sends `if_idle`.

200:
```json
{
  "state": "<43-char url-safe random>",
  "mode": "signin",
  "start_url": "https://accounts.google.com/EmbeddedSetup",
  "unlock_url": "https://accounts.google.com/encryption/unlock/android?kdi=...",
  "unlock_after_host": null,
  "expires_in": 600,
  "window": {
    "label": "signin-google",
    "title": "Find+ sign-in: Google (accounts.google.com)",
    "title_template": "Find+ sign-in: Google ({host})",
    "width": 480, "height": 720, "incognito": true,
    "poll_ms": 500, "stuck_after_seconds": 180, "timeout_seconds": 600,
    "cookie": {"name": "oauth_token", "value_prefix": "oauth2_4/", "domain_suffix": "google.com"},
    "bridge_host": "findplus-bridge.invalid"
  },
  "allowed_hosts": ["accounts.google.com", "accounts.youtube.com", "myaccount.google.com",
                    "ssl.gstatic.com", "www.google.com"],
  "allowed_host_pattern": "^(?:<label>\\.)*(?:google\\.com|gstatic\\.com|googleapis\\.com|googleusercontent\\.com|recaptcha\\.net|google\\.(?:[a-z]{2}|co\\.[a-z]{2}|com\\.[a-z]{2}))$",
  "generation": 3,
  "flow": "3f9a1c0b7d2e"
}
```
- `flow`: 12 hex characters naming this sign-in. Progress (§3.6) and the shell's `signin-progress`
  / `signin-result` events carry it; the card ignores news from any other flow (§3.8).
- `mode: "unlock"`: `start_url` is `https://accounts.google.com/`; wait until a page on
  `unlock_after_host` (`myaccount.google.com`) loads, then navigate to `unlock_url`.
- `mode: "signin"`: `unlock_after_host` is null; after a token answer with `needs_unlock: true`,
  navigate the same window to `unlock_url` (already signed in there).
- `unlock_url` is built by the vendored `get_security_domain_request_url()` and is single-session;
  it may be `null` in signin mode if the vendor could not build it (then close after sign-in; the
  card offers the other unlock paths).
- `allowed_hosts` / `allowed_host_pattern`: Google's sign-in pages and the frames they embed
  (`*.google.com`, `[sub.]google.<cc>`, `.co.<cc>`, `.com.<cc>`, `gstatic.com`, `googleapis.com`,
  `googleusercontent.com`, `recaptcha.net`, plus `accounts.youtube.com`). The shell keeps its own
  copy (`signin_hosts.rs`); look-alikes, IP literals, a port or a `user@` part never pass.
- Errors: 403 `bad_client` (no Origin), 409 `not_signed_in` (unlock mode, nobody signed in),
  409 `window_open` (`if_idle` and a window still working), 422 `bad_mode`, 503
  `unlock_unavailable` (unlock mode only), 401 locked.

### 3.2 token

`POST .../token` body `{"state": "...", "oauth_token": "oauth2_4/..."}`.
200: `{"result": "signed_in", "account": "you@gmail.com", "needs_unlock": true | false}`.
- `needs_unlock: false`: the state is burned. Show "Signed in" in the title, wipe, close.
- `needs_unlock: true`: the SAME state is now kind `native_unlock` with a fresh 10-minute TTL.
  Navigate to `unlock_url`; post `unlock` with that state.

| Status | code | Meaning | Shell action | Progress phase |
|---|---|---|---|---|
| 403 | `bad_client` / `state_invalid` | headers wrong / state unknown, expired, used, cancelled | wipe, close | unchanged |
| 400 | `token_rejected` | Google issued nothing | `event failed` | `error` |
| 422 | `token_malformed` | not an `oauth2_4/` value | state kept: keep polling | `waiting` (never `error`) |
| 502 | `google_unreachable` | network or Google timeout (60 s) | state kept: retry once, then `event failed` reason `google_unreachable` | `finishing`, "Google is slow to answer. Trying again..." (never `error`) |
| 500 | `signin_failed` | anything else | `event failed` | `error` |

A second concurrent post with the same state is `state_invalid` (one exchange at a time).

### 3.3 unlock

`POST .../unlock` body `{"state": "...", "vault_keys": <string or JSON>, "account_hint": "you@gmail.com" | null}`.
`vault_keys` is what the page passed to `window.mm.setVaultSharedKeys`. `account_hint` is the email the
bridge read from `myaccount.google.com`, if any (compared case-insensitively with the signed-in account).
200: `{"result": "unlocked", "account": "you@gmail.com"}`; the state is burned. Wipe, close.
Unlock-only mode (`begin` with `mode: "unlock"`) REQUIRES `account_hint`: without it the daemon
cannot know whose keys these are, so it answers 409 `account_unknown` and stores nothing (the
shell already stops before the unlock page when the account page shows no address, and reports
`event failed` reason `account_unknown`). After a sign-in in the same window the account is known
from the token answer, so no hint is needed.
Errors: 400 `keys_rejected` (no usable key in them), 409 `account_mismatch`, 409 `account_unknown`,
409 `not_signed_in`, 500 `unlock_failed`, 403 as above. 400/409/500 keep the state and set `error`.

### 3.4 event

`POST .../event` body `{"state": "...", "event": "<event>", "reason": "<word>" | null}`.

| event | Effect on the card | State |
|---|---|---|
| `opened`, `waiting` | `waiting` (signin kind) or `needs_unlock` (unlock kind) | kept |
| `blocked` | `blocked_embedded`; block remembered 7 days | dropped |
| `closed` | `cancelled`; but after a finished sign-in that still needed the unlock: `success` with `unlocked: false` (attention then says `unlock`) | dropped |
| `failed` | `error` with the reason's words | dropped |

`reason` for `blocked`: `rejected_page`, `disallowed_useragent`, `outside_google`, `other`. (`stuck`
is still accepted from an older shell, but the 1.2 shell never sends it: a window with no
activity for 3 minutes only adds a note on the card, `signin-progress` with `stuck: true`, and keeps
going, so a slow 2-step approval never burns the 7-day memory.) `outside_google` is sent only for
a top-level move off Google: a refused non-Google frame is logged, never reported (§3.5).
`reason` for `failed`: `load_failed`, `timeout`, `cookie_read_failed`, `bridge_bad`,
`account_unknown`, `google_unreachable`, `other`. Unknown reasons become `other`; `other` after a
refusal the daemon already explained (wrong account, unusable keys) keeps the daemon's words. 200: `{"phase", "message", "fallback"}`. 422 `bad_event`; 403 as above.
Post `opened` once the window shows, `closed` on Cmd+W or close, `failed`/`blocked` before wiping.

### 3.5 classify

`POST .../classify` body `{"state": "...", "host": "accounts.google.com", "path": "/v3/signin/rejected",
"title_class": "normal" | "couldnt_sign_in" | "browser_not_secure" | "unknown"}`.
Send ONLY the host and the path (no query, no fragment, max 512 chars) and a coarse class the shell
derives from the title. Never page text, never a full URL.
200: `{"blocked": bool, "reason": <blocked reason> | null, "action": "close" | "continue", "fallback": ...}`.
When `blocked` is true the daemon has already done what `event: blocked` does: wipe and close.
Blocked when: path contains `disallowed_useragent`; an `accounts.google.*` path starting
`/signin/rejected` or `/v3/signin/rejected`; `title_class` is `browser_not_secure`; or the host is
off the allow-list (`outside_google`, e.g. Workspace SSO). 422 `bad_report` for anything else.
Call it on every main-frame page load (and for a navigation the allow-list cancelled).

### 3.6 progress (the card polls this)

`GET .../progress` 200:
```json
{"phase": "waiting", "message": "Finish signing in in the Find+ window.", "mode": "signin",
 "account": null, "unlocked": false, "reason": null, "flow": "3f9a1c0b7d2e",
 "updated_at": "2026-10-02T09:00:00+00:00",
 "blocked_at": null, "start_with": "window", "fallback": null, "generation": 3}
```
Phases (spec §7): `idle`, `connecting` (after begin), `waiting`, `finishing` (token or keys being
checked), `needs_unlock`, `success`, `blocked_embedded`, `error`, plus `cancelled`. Terminal:
`idle`, `success`, `blocked_embedded`, `error`, `cancelled`. `start_with` is `helper` for 7 days
after a block (the card leads with the Chrome helper and a quiet "Try the Find+ window again").
`fallback` (the ladder): null while the window path is fine; `use_helper` after a block or an error;
`use_paste` when Chrome is missing or the helper also failed after the block. `generation` bumps on
every finished Google sign-in (helper or window). The same object is `google_native` in
`GET /api/auth/status`.

### 3.7 cancel

`POST .../cancel` (no body). Drops the native state; phase `cancelled` unless already terminal
(same exception as `closed` after a finished sign-in).
200 `{"phase", "message", "fallback"}`. Idempotent. The caller closes the window (Tauri command);
a later token post from that window gets 403 `state_invalid`. A token exchange already running when
cancel arrives still finishes: if Google signed the person in, the phase becomes `success` (with
`unlocked: false` when the unlock is still needed), because that is the truth; the state is never
re-kinded and the window closes. The card shows no Cancel during `finishing`.

### 3.8 Who owns the session state

The daemon's progress record (§3.6) is the ONLY truth. The shell reports what its window saw
(token, unlock, event, classify); the card reflects the progress (it polls, and uses the shell's
events only to be quick). Every write after a slow exchange is checked against the flow it
belongs to, so an older window can never paint over a newer sign-in.

| From | Trigger (who) | To | Notes |
|---|---|---|---|
| any | `begin` (card or shell) | `connecting` | new `flow`; older native states dropped. Card's `if_idle` begin while live: 409 `window_open`, no change |
| `connecting` | `event opened` / `waiting` (shell) | `waiting` (signin) / `needs_unlock` (unlock) | |
| `waiting` | `token` post (shell) | `finishing` | |
| `finishing` | token 200, no unlock needed | `success` (`unlocked: true`) | state burned |
| `finishing` | token 200, unlock needed | `needs_unlock` | same state, re-kinded, fresh 10 min |
| `finishing` | token 422 | `waiting` | shell keeps reading |
| `finishing` | token 502 | `finishing` ("slow") | shell retries once |
| `finishing` | token 400 / 500, unlock 400 / 409 / 500 | `error` | shell ends the window (`event failed`) |
| `needs_unlock` | `unlock` 200 | `success` (`unlocked: true`) | |
| live | `event blocked` / classify blocked | `blocked_embedded` | 7-day memory |
| live | `event failed` | `error` | |
| live | `event closed` / `cancel` (card) | `cancelled`; `success` (`unlocked: false`) from `needs_unlock` after a sign-in | |
| `cancelled` | token 200 that was already running | `success` | the sign-in really happened |
| live | the window's state is gone (app quit or crashed; 10-minute TTL) | `idle`; `success` (`unlocked: false`) from `needs_unlock` | applied on the next read |

Live phases: `connecting`, `waiting`, `finishing`, `needs_unlock`. The shell closes its window when
the daemon says `cancelled` or `idle`, or names another flow, while the person is on a Google
page; an exchange in flight always finishes. A begin the card hands over while a window is still
closing is held by the shell and opened right after (`open_signin_window` answers `queued`).

## 4. Lost sign-in: `attention`

`GET /api/auth/status` providers gain `attention` and `deep_link`; the top level gains
`deep_links` and `google_native`:
```json
{"providers": [{"id": "google-find-hub", "signed_in": false, "account": "you@gmail.com",
   "needs": ["reauth"], "attention": "reauth", "deep_link": "findplus://signin/google", "...": "..."},
  {"id": "apple-find-my", "attention": "none", "deep_link": null, "...": "..."}],
 "deep_links": {"findplus://signin/google": true, "findplus://unlock/google": false,
                "findplus://signin/apple": false},
 "google_native": {"phase": "idle", "...": "..."}}
```
`attention` is `"reauth"`, `"unlock"` or `"none"` (a string, never null):
- Google `reauth`: Google refused the saved login (`auth_revoked` mark: revoked access, password change),
  or the newest poll of a Google device was refused for its sign-in (`last_error_type` `auth`, stored
  as `AuthRequiredError` / `unauthenticated`) after the last saved sign-in.
- Google `unlock`: signed in but the location key is missing or belongs to another account (key reset).
- Apple `reauth`: Apple refused the saved session during a poll (marker cleared by the next sign-in or
  a sign-out), the newest poll of an Apple device was refused for its sign-in after the last saved
  sign-in, or the saved session never finished signing in.
- `none`: healthy, or never signed in (the Connect button covers that; no banner).

`/api/status` `provider_health` rows carry the same `attention` (the tray already polls it; the
MCP `get_status` tool shows it). Raise the native banner on the transition from `none` to anything
else, once per loss.

Deep links: open the login only while `deep_links[url]` is true; otherwise open Settings > Sign-in.
While the app is locked `/api/auth/status` is 401: treat every deep link as "open Settings" (the main
window then shows the lock screen first).
`findplus://signin/google` -> window `mode: "signin"`; `findplus://unlock/google` -> `mode: "unlock"`;
`findplus://signin/apple` -> dashboard with the Apple sheet open.

## 5. Apple sheet

Existing, unchanged: `POST /api/auth/apple/start {apple_id, password}` -> 202 `{job_id}`;
`POST /api/auth/apple/code {job_id, code}`; `GET /api/auth/apple/progress?job_id=`.
New:
- `GET /api/auth/apple/status[?job_id=]` (newest job when omitted) ->
  `{"job_id", "phase", "message", "account", "second_factor", "attempts_left", "available", "install_hint"}`.
  Phases: `idle`, `preparing` (first-run anisette download), `signing_in`, `needs_code`, `success`,
  `error`, `cancelled`. `second_factor` (only in `needs_code`):
  `{"kind": "trusted_device" | "sms", "phone": "<masked, as Apple sends it>" | null, "can_text": bool,
  "sms_options": [{"id": 7, "phone": "+1 (•••) •••-••12"}]}`.
  Trusted device message: "Enter the 6-digit code shown on your iPhone, iPad or Mac."
- `POST /api/auth/apple/text {job_id, phone_id?}` ("Text me instead") -> `{"phase": "needs_code",
  "message", "phone"}`; 404 unknown job, 409 not waiting for a code, 422 no such number, 502 Apple did
  not send.
- `POST /api/auth/apple/cancel {job_id}` -> `{"phase": "cancelled", "message": "Cancelled. Nothing changed."}`;
  404 when unknown or already over. A cancel during login saves nothing.
Both POSTs need `Origin` or `Sec-Fetch-Site`; all three are behind the app lock. The password is
never in any response.

## 6. CLI and MCP

`findplus auth --status` adds a "Needs" column (`sign in again`, `unlock`, `-`) and, while a window
flow is active, one line with the window's phase and message plus the next fallback command
(`findplus auth --helper` or `findplus auth --token`). `--json` prints the same object as
`GET /api/auth/status`. MCP tools are unchanged; `get_status` shows `attention` per provider.
