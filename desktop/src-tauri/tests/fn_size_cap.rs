//! Scans every `src/**/*.rs` file for a function body longer than 50 lines.
//!
//! Purpose    : Enforce PRI hard rule 7 (functions <=50 lines) mechanically,
//!              so a future regression like C1's status.rs::from_api() (76
//!              lines) fails `cargo test` instead of only a manual review
//!              catching it (loop2 C1).
//! Inputs     : Every `.rs` file under `desktop/src-tauri/src/`, found via
//!              `CARGO_MANIFEST_DIR` at test time.
//! Outputs    : Panics, naming every offending file, line and function, when
//!              any function body exceeds 50 lines.
//! Constraints: Line-based, not a real parser: it finds a `fn` signature
//!              (possibly spanning several lines) then counts brace depth
//!              from the opening `{` to the matching `}`. Good enough for
//!              this crate's rustfmt-formatted style; nested functions are
//!              measured as part of their enclosing function, not counted
//!              twice.

use std::fs;
use std::path::Path;

const MAX_FN_LINES: usize = 50;

#[test]
fn no_function_in_src_exceeds_fifty_lines() {
    let src_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut offenders = Vec::new();
    scan_dir(&src_dir, &mut offenders);
    assert!(
        offenders.is_empty(),
        "functions over {MAX_FN_LINES} lines (PRI hard rule 7):\n{}",
        offenders.join("\n")
    );
}

fn scan_dir(dir: &Path, offenders: &mut Vec<String>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            scan_dir(&path, offenders);
        } else if path.extension().and_then(|e| e.to_str()) == Some("rs") {
            scan_file(&path, offenders);
        }
    }
}

fn scan_file(path: &Path, offenders: &mut Vec<String>) {
    let Ok(contents) = fs::read_to_string(path) else {
        return;
    };
    let lines: Vec<&str> = contents.lines().collect();
    let mut i = 0;
    while i < lines.len() {
        if is_fn_signature_start(lines[i]) {
            if let Some((name, end_line, len)) = measure_fn(&lines, i) {
                if len > MAX_FN_LINES {
                    offenders.push(format!(
                        "{}:{} `{}` -- {} lines",
                        path.display(),
                        i + 1,
                        name,
                        len
                    ));
                }
                i = end_line;
                continue;
            }
        }
        i += 1;
    }
}

/// True when this line looks like the start of a function signature — not a
/// call, not a doc comment, not an attribute.
fn is_fn_signature_start(line: &str) -> bool {
    let trimmed = line.trim_start();
    if trimmed.starts_with("//") || trimmed.starts_with('#') {
        return false;
    }
    ["fn ", "pub fn ", "async fn ", "pub async fn ", "pub(crate) fn "]
        .iter()
        .any(|prefix| trimmed.starts_with(prefix))
}

/// From the signature start line, find the function's `{ ... }` body.
/// Returns (name, index of the closing-brace line, line count from the
/// signature to that closing brace, inclusive). None for a signature with no
/// body (a trait method declaration ending in `;`).
fn measure_fn(lines: &[&str], start: usize) -> Option<(String, usize, usize)> {
    let name = fn_name(lines[start]);
    let mut depth = 0i32;
    let mut seen_brace = false;
    let mut i = start;
    while i < lines.len() {
        for ch in lines[i].chars() {
            match ch {
                '{' => {
                    depth += 1;
                    seen_brace = true;
                }
                '}' => depth -= 1,
                _ => {}
            }
        }
        if seen_brace && depth <= 0 {
            return Some((name, i, i - start + 1));
        }
        if !seen_brace && lines[i].trim_end().ends_with(';') {
            return None;
        }
        i += 1;
    }
    None
}

fn fn_name(line: &str) -> String {
    let after_fn = line.split("fn ").nth(1).unwrap_or("");
    after_fn.split(['(', '<']).next().unwrap_or("").trim().to_string()
}
