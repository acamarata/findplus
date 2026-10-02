//! In-app sign-in: fake Google pages and fake daemon routes (debug builds only).
//!
//! Purpose    : Let the real sign-in window run end to end on 127.0.0.1 with no
//!              Google and no daemon: EmbeddedSetup that sets an HttpOnly
//!              `oauth_token=oauth2_4/test`, an account page, an unlock page that
//!              calls `window.mm.setVaultSharedKeys`, a rejection page, and the
//!              four native routes (begin/token/unlock/event) that check what
//!              Rust posts.
//! Constraints: Compiled only with `debug_assertions`. One listener, one
//!              thread per connection, `Connection: close`. `respond` is pure.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};

pub const FAKE_TOKEN: &str = "oauth2_4/test";
pub const FAKE_VAULT: &str = r#"[{"fake":"vault"}]"#;
pub const FAKE_ACCOUNT: &str = "fake@example.com";

/// Start the server for one self-test case ("reject": EmbeddedSetup redirects
/// to a rejection page; "cancel": it never advances; else it signs in after
/// 1 s). Returns its base URL (`http://127.0.0.1:<port>`).
pub fn start(case: &str) -> Option<String> {
    let case = case.to_string();
    let listener = TcpListener::bind("127.0.0.1:0").ok()?;
    let base = format!("http://127.0.0.1:{}", listener.local_addr().ok()?.port());
    let b = base.clone();
    std::thread::spawn(move || {
        for conn in listener.incoming().flatten() {
            let (b, case) = (b.clone(), case.clone());
            std::thread::spawn(move || serve(conn, &b, &case));
        }
    });
    Some(base)
}

fn serve(mut conn: TcpStream, base: &str, case: &str) {
    let mut buf = Vec::new();
    let mut chunk = [0u8; 4096];
    while let Ok(n) = conn.read(&mut chunk) {
        if n == 0 {
            break;
        }
        buf.extend_from_slice(&chunk[..n]);
        if request_complete(&buf) {
            break;
        }
    }
    let req = String::from_utf8_lossy(&buf).to_string();
    let path = req.split_whitespace().nth(1).unwrap_or("/").to_string();
    let (head, body) = req.split_once("\r\n\r\n").unwrap_or((&req, ""));
    let shell_only = path.starts_with(SHELL_ONLY) && !path.ends_with("/begin");
    let resp = if !shell_only || shell_headers_ok(head, base) {
        respond(&path, body, base, case)
    } else {
        json(
            403,
            r#"{"detail":"fake daemon: not the sign-in window","code":"bad_client"}"#,
        )
    };
    let _ = conn.write_all(resp.as_bytes());
}

/// The shell-only routes: everything under this prefix except begin.
const SHELL_ONLY: &str = "/api/auth/google/native/";

/// Pure: the pinned headers the real daemon requires (Origin + client header).
fn shell_headers_ok(head: &str, base: &str) -> bool {
    let lower = format!("{}\r\n", head.to_lowercase());
    lower.contains(&format!("\r\norigin: {base}\r\n"))
        && lower.contains("\r\nx-findplus-client: signin-window\r\n")
}

/// Pure: headers read and the whole Content-Length body present.
fn request_complete(buf: &[u8]) -> bool {
    let text = String::from_utf8_lossy(buf);
    let Some((head, body)) = text.split_once("\r\n\r\n") else {
        return false;
    };
    let len = head
        .lines()
        .find_map(|l| {
            l.to_lowercase()
                .strip_prefix("content-length:")
                .map(|v| v.trim().to_string())
        })
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(0);
    body.len() >= len
}

/// Pure: the full HTTP response for one request.
pub fn respond(path: &str, body: &str, base: &str, case: &str) -> String {
    let path = path.split('?').next().unwrap_or("/");
    let v: serde_json::Value = serde_json::from_str(body).unwrap_or_default();
    match path {
        "/EmbeddedSetup" if case == "reject" => redirect("/v3/signin/rejected"),
        "/EmbeddedSetup" if case == "cancel" => page("Sign in", "<h1>Fake sign-in</h1>", "", ""),
        "/EmbeddedSetup" => page(
            "Sign in",
            "<h1>Fake sign-in</h1>",
            "<meta http-equiv=refresh content=1;url=/EmbeddedSetup/done>",
            "",
        ),
        "/EmbeddedSetup/done" => page(
            "Signed in",
            "<h1>Signed in (fake)</h1>",
            "",
            &format!("Set-Cookie: oauth_token={FAKE_TOKEN}; Path=/; HttpOnly\r\n"),
        ),
        "/v3/signin/rejected" => page(
            "Couldn't sign you in",
            "<p>This browser or app may not be secure.</p>",
            "",
            "",
        ),
        "/" => redirect("/myaccount"),
        "/myaccount" => page(
            "Account",
            &format!(
                "<a aria-label=\"Recovery: r@example.org\" href=#>r</a>\
                 <a aria-label=\"Google Account: Test ({FAKE_ACCOUNT})\" \
                 href=\"/SignOutOptions?hl=en\">me</a>"
            ),
            "",
            "",
        ),
        "/encryption/unlock/android" => page("Unlock", UNLOCK_BODY, "", ""),
        "/api/auth/google/native/begin" => json(
            200,
            &format!(r#"{{"state":"st-1","unlock_url":"{base}/encryption/unlock/android?kdi=x"}}"#),
        ),
        "/api/auth/google/native/token" => token_reply(&v),
        "/api/auth/google/native/unlock" => unlock_reply(&v),
        "/api/auth/google/native/event" => json(200, r#"{"ok":true}"#),
        "/api/auth/google/native/classify" => json(200, r#"{"blocked":false,"reason":null}"#),
        _ => "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_string(),
    }
}

const UNLOCK_BODY: &str = "<h1>Fake unlock</h1><script>setTimeout(function(){\
 if (window.mm) { window.mm.setVaultSharedKeys('x', [{fake:'vault'}]); window.mm.closeView(); }\
 else { document.title = 'no bridge'; } }, 300);</script>";

fn token_reply(v: &serde_json::Value) -> String {
    if v["state"] == "st-1" && v["oauth_token"] == FAKE_TOKEN {
        json(
            200,
            &format!(r#"{{"account":"{FAKE_ACCOUNT}","needs_unlock":true}}"#),
        )
    } else {
        json(400, r#"{"detail":"fake daemon: wrong state or token"}"#)
    }
}

fn unlock_reply(v: &serde_json::Value) -> String {
    let hint = v.get("account_hint").filter(|a| !a.is_null());
    let account_ok = hint.is_none_or(|a| a == FAKE_ACCOUNT);
    if v["state"] == "st-1" && v["vault_keys"] == FAKE_VAULT && account_ok {
        json(200, r#"{"state":"done"}"#)
    } else {
        json(
            400,
            r#"{"detail":"fake daemon: wrong state, keys or account"}"#,
        )
    }
}

fn page(title: &str, body: &str, head: &str, extra: &str) -> String {
    let html = format!("<!doctype html><title>{title}</title>{head}{body}");
    format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n{extra}Content-Length: {}\r\nConnection: close\r\n\r\n{html}",
        html.len()
    )
}

fn json(status: u16, body: &str) -> String {
    format!(
        "HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )
}

fn redirect(to: &str) -> String {
    format!(
        "HTTP/1.1 302 Found\r\nLocation: {to}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cookie_only_after_the_sign_in_page() {
        assert!(!respond("/EmbeddedSetup", "", "b", "ok").contains("Set-Cookie"));
        assert!(respond("/EmbeddedSetup/done", "", "b", "ok").contains("oauth_token=oauth2_4/test"));
        assert!(respond("/EmbeddedSetup", "", "b", "reject").starts_with("HTTP/1.1 302"));
    }

    #[test]
    fn fake_daemon_checks_what_rust_posts() {
        let ok = r#"{"state":"st-1","oauth_token":"oauth2_4/test"}"#;
        assert!(respond("/api/auth/google/native/token", ok, "b", "ok").starts_with("HTTP/1.1 200"));
        let bad = r#"{"state":"st-2","oauth_token":"oauth2_4/test"}"#;
        assert!(
            respond("/api/auth/google/native/token", bad, "b", "ok").starts_with("HTTP/1.1 400")
        );
        let keys = r#"{"state":"st-1","vault_keys":"[{\"fake\":\"vault\"}]"}"#;
        assert!(
            respond("/api/auth/google/native/unlock", keys, "b", "ok").starts_with("HTTP/1.1 200")
        );
        assert!(request_complete(
            b"POST / HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}"
        ));
        assert!(!request_complete(
            b"POST / HTTP/1.1\r\nContent-Length: 5\r\n\r\n{}"
        ));
    }
}
