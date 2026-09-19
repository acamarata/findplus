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
