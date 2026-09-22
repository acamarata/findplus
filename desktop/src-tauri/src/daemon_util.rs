//! Small process/file helpers shared by daemon.rs: the current uid (for
//! `launchctl kickstart`), a pid liveness probe, and daemon.json parsing.
//! Split out of daemon.rs to keep it under the 300-line file cap.

use serde_json::Value;
use std::io::Read;
use std::process::Command;

// Avoid a libc dependency for one syscall: shell out to `id -u`.
pub fn current_uid() -> u32 {
    Command::new("id")
        .arg("-u")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0)
}

pub fn read_daemon_json_pid() -> Option<u32> {
    let home = dirs::home_dir()?;
    let path = home.join(".findplus/daemon.json");
    let mut f = std::fs::File::open(path).ok()?;
    let mut s = String::new();
    f.read_to_string(&mut s).ok()?;
    let v: Value = serde_json::from_str(&s).ok()?;
    v.get("pid").and_then(|p| p.as_u64()).map(|p| p as u32)
}

pub fn pid_alive(pid: u32) -> bool {
    Command::new("/bin/kill")
        .arg("-0")
        .arg(pid.to_string())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// The daemon's port: `FINDPLUS_PORT` if set to a valid u16, else the same
/// key (bare `PORT` or prefixed `FINDPLUS_PORT`, both legal there -- see
/// findplus.config_keys.unprefixed_config_env) in `~/.findplus/config.env`,
/// else `default_port`. Resolved once per process (daemon.rs caches it in a
/// OnceLock): the app reads this before it ever probes or spawns the
/// daemon, not while the daemon is already running (G2).
pub fn resolved_port(default_port: u16) -> u16 {
    if let Some(port) = std::env::var("FINDPLUS_PORT")
        .ok()
        .and_then(|raw| parse_port(&raw))
    {
        return port;
    }
    config_env_port().unwrap_or(default_port)
}

fn parse_port(raw: &str) -> Option<u16> {
    raw.trim().parse().ok()
}

/// The `PORT` or `FINDPLUS_PORT` value out of a config.env's text, or None
/// when neither key is present or its value doesn't parse. A pure function
/// over the file's contents so it is testable without touching the real
/// home directory.
fn port_from_config_env_text(text: &str) -> Option<u16> {
    for line in text.lines() {
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        let key = key.trim().to_ascii_uppercase();
        if key == "PORT" || key == "FINDPLUS_PORT" {
            if let Some(port) = parse_port(value) {
                return Some(port);
            }
        }
    }
    None
}

fn config_env_port() -> Option<u16> {
    let home = dirs::home_dir()?;
    let text = std::fs::read_to_string(home.join(".findplus/config.env")).ok()?;
    port_from_config_env_text(&text)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn config_env_text_reads_the_bare_port_key() {
        assert_eq!(port_from_config_env_text("HOST=127.0.0.1\nPORT=9001\n"), Some(9001));
    }

    #[test]
    fn config_env_text_reads_the_prefixed_port_key_case_insensitively() {
        assert_eq!(port_from_config_env_text("findplus_port=9002"), Some(9002));
    }

    #[test]
    fn config_env_text_ignores_an_unparsable_port_value() {
        assert_eq!(port_from_config_env_text("PORT=not-a-number"), None);
    }

    #[test]
    fn config_env_text_ignores_lines_with_no_equals_sign() {
        assert_eq!(port_from_config_env_text("# a comment\nPORT=9003"), Some(9003));
    }

    #[test]
    fn config_env_text_with_neither_key_is_none() {
        assert_eq!(port_from_config_env_text("HOST=127.0.0.1\n"), None);
    }

    #[test]
    fn resolved_port_prefers_a_valid_env_var_over_the_default() {
        // Returns before config_env_port() is ever called, so this never
        // touches the real ~/.findplus/config.env (PRI hard rule 3's intent,
        // applied here even though this is a Rust, not a pytest, suite).
        std::env::set_var("FINDPLUS_PORT", "9100");
        let result = resolved_port(8647);
        std::env::remove_var("FINDPLUS_PORT");
        assert_eq!(result, 9100);
    }
}
