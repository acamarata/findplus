//! Package 0 gate probe: fake EmbeddedSetup server (debug builds only).
//!
//! Purpose    : Let the probe run end to end on 127.0.0.1 with no Google.
//!              FINDPLUS_PROBE_FAKE=ok serves a page whose button leads to a
//!              response that sets an HttpOnly `oauth_token` cookie (`ok-auto`
//!              follows the button by itself, for unattended runs);
//!              FINDPLUS_PROBE_FAKE=reject redirects to a rejection page.
//! Constraints: Compiled only with `debug_assertions`; a release build has
//!              no way to point the probe anywhere but Google. The cookie
//!              value is an obvious test string.
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};

/// Start the server when FINDPLUS_PROBE_FAKE is `ok` or `reject`.
/// Returns the start URL, or None when the variable is unset or unknown.
pub fn start_from_env() -> Option<String> {
    let mode = std::env::var("FINDPLUS_PROBE_FAKE").ok()?;
    if !["ok", "ok-auto", "reject"].contains(&mode.as_str()) {
        return None;
    }
    let listener = TcpListener::bind("127.0.0.1:0").ok()?;
    let port = listener.local_addr().ok()?.port();
    std::thread::spawn(move || {
        for conn in listener.incoming().flatten() {
            let (reject, auto) = (mode == "reject", mode == "ok-auto");
            std::thread::spawn(move || serve(conn, reject, auto));
        }
    });
    Some(format!("http://127.0.0.1:{port}/EmbeddedSetup"))
}

fn serve(mut conn: TcpStream, reject: bool, auto: bool) {
    let mut buf = [0u8; 2048];
    let n = conn.read(&mut buf).unwrap_or(0);
    let req = String::from_utf8_lossy(&buf[..n]);
    let path = req.split_whitespace().nth(1).unwrap_or("/");
    let mut resp = respond(path, reject);
    if auto && path == "/EmbeddedSetup" {
        resp = resp.replace("<title>", "<meta http-equiv=refresh content=1;url=/EmbeddedSetup/done><title>");
    }
    let _ = conn.write_all(resp.as_bytes());
}

/// Pure: the full HTTP response for one path.
pub fn respond(path: &str, reject: bool) -> String {
    let path = path.split('?').next().unwrap_or("/");
    match (path, reject) {
        ("/EmbeddedSetup", true) => redirect("/v3/signin/rejected"),
        ("/v3/signin/rejected", _) => page(
            "Couldn't sign you in",
            "<h1>Couldn't sign you in</h1><p>This browser or app may not be secure.</p>",
            "",
        ),
        ("/EmbeddedSetup", false) => page(
            "Fake EmbeddedSetup",
            "<h1>Fake Google sign-in</h1><form action=\"/EmbeddedSetup/done\"><button>Sign in (test)</button></form>",
            "",
        ),
        ("/EmbeddedSetup/done", _) => page(
            "Fake signed in",
            "<h1>Signed in (fake)</h1><p>The probe should now see the cookie.</p>",
            "Set-Cookie: oauth_token=oauth2_4/FAKE-TEST-VALUE; Path=/; HttpOnly\r\n",
        ),
        _ => "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_string(),
    }
}

fn page(title: &str, body: &str, extra: &str) -> String {
    let html = format!("<!doctype html><title>{title}</title>{body}");
    format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n{extra}Content-Length: {}\r\nConnection: close\r\n\r\n{html}",
        html.len()
    )
}

fn redirect(to: &str) -> String {
    format!("HTTP/1.1 302 Found\r\nLocation: {to}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ok_mode_sets_cookie_only_after_the_click() {
        assert!(!respond("/EmbeddedSetup", false).contains("Set-Cookie"));
        assert!(respond("/EmbeddedSetup/done", false).contains("Set-Cookie: oauth_token=oauth2_4/"));
    }

    #[test]
    fn reject_mode_redirects_to_a_rejection_page() {
        assert!(respond("/EmbeddedSetup", true).starts_with("HTTP/1.1 302"));
        assert!(respond("/v3/signin/rejected", true).contains("may not be secure"));
    }
}
