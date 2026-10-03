//! Install a staged update: ask the daemon to back up, check the new app, then
//! hand over to update-app.sh and quit so it can swap the bundle.
//!
//! Purpose    : The one path every install takes (automatic, tray item, the
//!              dashboard's Restart to update and Settings' Update now).
//! Inputs     : POST /api/update/apply (verified build + preupdate backup), the
//!              running executable's path, update-app.sh compiled into this app.
//! Outputs    : A detached `bash update-app.sh --wait-pid <us>` that outlives
//!              this process; then this process stops its daemon and exits.
//! Constraints: Every refusal (no bundle, backup failed, wrong team, bad
//!              signature) happens BEFORE anything quits: `--verify-only` runs
//!              first and a failure is written to the result file, so the
//!              daemon stops offering that build automatically. The script runs
//!              from `~/.findplus/updates`, not from inside the bundle it replaces.

use std::fs;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use super::logic::{bundle_parent, last_line, parse_apply, script_args, Apply};

/// update-app.sh as it was when this app was built (and signed).
const SCRIPT: &str = include_str!("../../../packaging/scripts/update-app.sh");
static APPLYING: AtomicBool = AtomicBool::new(false);

fn request_apply() -> Result<Apply, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(180)) // a large database takes a while to back up
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .post(format!("{}/api/update/apply", crate::daemon::daemon_base()))
        .header("X-FindPlus-Client", "updater")
        .send()
        .map_err(|_| "Find+ could not reach its background service.".to_string())?;
    let code = resp.status().as_u16();
    let body = resp.json::<serde_json::Value>().unwrap_or_default();
    parse_apply(code, &body)
}

fn write_script(dir: &Path) -> Result<PathBuf, String> {
    let path = dir.join("update-app.sh");
    fs::write(&path, SCRIPT).map_err(|e| format!("Could not prepare the installer: {e}"))?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).map_err(|e| e.to_string())?;
    Ok(path)
}

fn bash(args: &[String], app_dir: &Path) -> Command {
    let mut cmd = Command::new("/bin/bash");
    cmd.args(args).env("APP_DIR", app_dir).stdin(Stdio::null());
    cmd
}

/// Run every check in update-app.sh; on a refusal, record it for the daemon.
fn verify(script: &Path, apply: &Apply, app_dir: &Path) -> Result<(), String> {
    let out = bash(&script_args(script, apply, None), app_dir)
        .output()
        .map_err(|e| format!("Could not run the installer: {e}"))?;
    if out.status.success() {
        return Ok(());
    }
    let reason = last_line(&String::from_utf8_lossy(&out.stderr));
    let _ = fs::write(&apply.result_file, format!("failed {reason}\n"));
    Err(reason)
}

/// Start the real install, detached in its own process group, logging beside it.
fn launch(script: &Path, apply: &Apply, app_dir: &Path) -> Result<(), String> {
    let dir = script.parent().unwrap_or(Path::new("/tmp"));
    let mut log = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("update.log"))
        .map_err(|e| e.to_string())?;
    let _ = writeln!(log, "--- Find+ update to {}", apply.version);
    let err = log.try_clone().map_err(|e| e.to_string())?;
    bash(
        &script_args(script, apply, Some(std::process::id())),
        app_dir,
    )
    .stdout(log)
    .stderr(err)
    .process_group(0)
    .spawn()
    .map(|_| ())
    .map_err(|e| format!("Could not start the installer: {e}"))
}

fn run(app_dir: &Path) -> Result<String, String> {
    let apply = request_apply()?;
    let dir = Path::new(&apply.result_file)
        .parent()
        .ok_or("Find+ sent an update it could not read.")?
        .to_path_buf();
    let script = write_script(&dir)?;
    verify(&script, &apply, app_dir)?;
    launch(&script, &apply, app_dir)?;
    Ok(apply.version)
}

/// Quit so the installer can swap the bundle: stop our own daemon, then exit.
fn quit_for_install() {
    std::thread::spawn(|| {
        std::thread::sleep(Duration::from_millis(800)); // let the caller's reply reach the page
        crate::daemon::stop_child();
        for _ in 0..40 {
            if !crate::daemon::child_running() {
                break;
            }
            std::thread::sleep(Duration::from_millis(250));
        }
        std::process::exit(0);
    });
}

/// Install the staged update. Ok(version) means the installer is running and
/// Find+ is about to quit; Err is a plain-words reason and nothing changed.
pub fn install() -> Result<String, String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let app_dir = bundle_parent(&exe)
        .ok_or("Updates install only into an installed Find+.app.".to_string())?;
    if APPLYING.swap(true, Ordering::SeqCst) {
        return Err("An update is already being installed.".into());
    }
    match run(&app_dir) {
        Ok(version) => {
            log::info!("updater: installing Find+ {version}; quitting");
            quit_for_install();
            Ok(version)
        }
        Err(e) => {
            APPLYING.store(false, Ordering::SeqCst);
            log::warn!("updater: install refused: {e}");
            Err(e)
        }
    }
}
