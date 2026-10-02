//! In-app sign-in: the init script for the sign-in window (pure string builder).
//!
//! Purpose    : Give the vendored unlock page the Android-style `window.mm`
//!              hook it calls (setVaultSharedKeys, closeView), report which
//!              account is signed in on the account page, and turn Cmd+W into
//!              Cancel. Every message leaves the page as a navigation to
//!              https://findplus-bridge.invalid/..., which the Rust navigation
//!              handler cancels before any request is made (spec §4).
//! Constraints: No Tauri IPC is used or reachable: the window has no
//!              capability, and this script never touches `window.__TAURI__`.
//!              It never reads or fills form fields. `window.mm` is defined
//!              only on the unlock page's own origin and path.

/// The origin the unlock page must be served from, and the account page's.
pub struct ScriptOrigins<'a> {
    pub unlock: &'a str,
    pub account: &'a str,
    /// Path prefix of the account page (empty for the real one).
    pub account_path: &'a str,
}

/// Production origins. A debug self-test passes its fake server instead.
pub const GOOGLE_ORIGINS: ScriptOrigins<'static> = ScriptOrigins {
    unlock: "https://accounts.google.com",
    account: "https://myaccount.google.com",
    account_path: "/",
};

const TEMPLATE: &str = r#"(function () {
  if (window.top !== window) { return; }
  var UNLOCK = __UNLOCK__, ACCOUNT = __ACCOUNT__, ACCOUNT_PATH = __ACCOUNT_PATH__;
  var BRIDGE = 'https://findplus-bridge.invalid/';
  function enc(s) {
    var b = new TextEncoder().encode(s), bin = '';
    for (var i = 0; i < b.length; i++) { bin += String.fromCharCode(b[i]); }
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function send(kind, data) {
    location.replace(BRIDGE + kind + (data === undefined ? '' : '#' + enc(data)));
  }
  document.addEventListener('keydown', function (e) {
    var w = e.key === 'w' || e.key === 'W';
    if (w && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey) {
      e.preventDefault(); e.stopPropagation(); send('cancel');
    }
  }, true);
  if (location.origin === UNLOCK && location.pathname.indexOf('/encryption/unlock/') === 0) {
    var sent = false;
    window.mm = {
      setVaultSharedKeys: function (_str, vaultKeys) {
        if (sent) { return; }
        sent = true;
        send('vault', typeof vaultKeys === 'string' ? vaultKeys : JSON.stringify(vaultKeys));
      },
      closeView: function () {
        setTimeout(function () { if (!sent) { sent = true; send('close'); } }, 400);
      }
    };
  }
  if (location.origin === ACCOUNT && location.pathname.indexOf(ACCOUNT_PATH) === 0) {
    var tries = 0;
    var look = setInterval(function () {
      var a = document.querySelector('a[aria-label*="@"], [data-email]');
      var text = a ? (a.getAttribute('data-email') || a.getAttribute('aria-label') || '') : '';
      var m = text.match(/[^\s()<>]+@[^\s()<>]+\.[A-Za-z]{2,}/);
      if (m) { clearInterval(look); send('account', m[0]); }
      else if (++tries > 20) { clearInterval(look); send('noaccount'); }
    }, 250);
  }
})();"#;

/// Pure: a JSON string literal, safe to splice into the script.
fn js_string(s: &str) -> String {
    serde_json::to_string(s).unwrap_or_else(|_| "\"\"".to_string())
}

/// Pure: the init script for the given origins.
pub fn init_script(o: &ScriptOrigins) -> String {
    TEMPLATE
        .replace("__UNLOCK__", &js_string(o.unlock))
        .replace("__ACCOUNT_PATH__", &js_string(o.account_path))
        .replace("__ACCOUNT__", &js_string(o.account))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn production_script_names_only_google_origins() {
        let s = init_script(&GOOGLE_ORIGINS);
        assert!(s.contains("\"https://accounts.google.com\""));
        assert!(s.contains("\"https://myaccount.google.com\""));
        assert!(!s.contains("__UNLOCK__") && !s.contains("__ACCOUNT"));
        assert!(!s.contains("127.0.0.1"));
    }

    #[test]
    fn script_never_touches_tauri_ipc_or_form_fields() {
        let s = init_script(&GOOGLE_ORIGINS);
        for banned in ["__TAURI__", "invoke", "ipc", "input", "password", ".value"] {
            assert!(!s.contains(banned), "script mentions {banned}");
        }
        assert!(s.contains("window.mm = {"));
        assert!(s.contains("https://findplus-bridge.invalid/"));
    }

    #[test]
    fn origins_are_escaped_as_json() {
        let o = ScriptOrigins {
            unlock: "a\"b",
            account: "c",
            account_path: "/",
        };
        assert!(init_script(&o).contains("\"a\\\"b\""));
    }
}
