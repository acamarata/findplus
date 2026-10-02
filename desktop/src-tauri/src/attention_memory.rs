//! Lost sign-in: which losses already had their banner, kept across app starts.
//!
//! Purpose    : Spec Q5 says ONE native banner per loss. The app used to start
//!              with "healthy" in memory, so every launch while a provider was
//!              still signed out counted as a new loss and showed the banner
//!              again (r12 #8). This keeps a tiny file: for each provider,
//!              whether the current loss was already announced. It is cleared
//!              when the provider is healthy again.
//! Inputs     : The attention just read; the file
//!              `<state dir>/app-attention-notified.json` (FINDPLUS_STATE_DIR,
//!              else ~/.findplus, the daemon's own state dir).
//! Outputs    : `due()` (pure); `load()` / `save()`.
//! Constraints: Holds two booleans, nothing else (no account, no place).
//!              A missing or broken file reads as "nothing announced yet".

use std::path::{Path, PathBuf};

use crate::attention::{Attention, Need, Provider};

pub const FILE: &str = "app-attention-notified.json";

/// Whether each provider's current loss was already announced.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Notified {
    pub google: bool,
    pub apple: bool,
}

impl Notified {
    fn get(&self, p: Provider) -> bool {
        match p {
            Provider::Google => self.google,
            Provider::Apple => self.apple,
        }
    }
}

/// Pure: the banners due now and the memory to keep. A provider gets one
/// banner when it starts needing attention (sign in or unlock: one loss),
/// and its memory clears once it is healthy again.
pub fn due(notified: Notified, next: &Attention) -> (Vec<(Provider, Need)>, Notified) {
    let banners = [Provider::Google, Provider::Apple]
        .into_iter()
        .filter_map(|p| next.get(p).filter(|_| !notified.get(p)).map(|n| (p, n)))
        .collect();
    let keep = Notified {
        google: next.google.is_some(),
        apple: next.apple.is_some(),
    };
    (banners, keep)
}

/// The memory file: the daemon's state dir (FINDPLUS_STATE_DIR, else ~/.findplus).
pub fn path() -> Option<PathBuf> {
    match std::env::var_os("FINDPLUS_STATE_DIR") {
        Some(dir) if !dir.is_empty() => Some(PathBuf::from(dir).join(FILE)),
        _ => dirs::home_dir().map(|h| h.join(".findplus").join(FILE)),
    }
}

/// The memory at `path`; nothing announced when it is missing or unreadable.
pub fn load(path: &Path) -> Notified {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

/// Write the memory (best effort, owner-only). Never panics.
pub fn save(path: &Path, notified: Notified) {
    let Ok(text) = serde_json::to_string(&notified) else {
        return;
    };
    if std::fs::write(path, text).is_ok() {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn att(google: Option<Need>, apple: Option<Need>) -> Attention {
        Attention { google, apple }
    }

    #[test]
    fn one_banner_per_loss_even_across_app_starts() {
        let lost = att(Some(Need::Signin), None);
        let (banners, mem) = due(Notified::default(), &lost);
        assert_eq!(banners, vec![(Provider::Google, Need::Signin)]);
        // The app quits and starts again, still signed out: no second banner.
        let (banners, mem) = due(mem, &lost);
        assert!(banners.is_empty());
        // Sign in -> unlock is the same loss continuing.
        let (banners, mem) = due(mem, &att(Some(Need::Unlock), None));
        assert!(banners.is_empty());
        // Healthy clears it; the next loss gets its own banner.
        let (banners, mem) = due(mem, &Attention::default());
        assert!(banners.is_empty() && mem == Notified::default());
        let (banners, _) = due(mem, &att(None, Some(Need::Signin)));
        assert_eq!(banners, vec![(Provider::Apple, Need::Signin)]);
    }

    #[test]
    fn the_file_round_trips_and_a_broken_one_reads_empty() {
        let dir = std::env::temp_dir().join(format!("fp-attn-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join(FILE);
        assert_eq!(load(&file), Notified::default());
        let mem = Notified {
            google: true,
            apple: false,
        };
        save(&file, mem);
        assert_eq!(load(&file), mem);
        let text = std::fs::read_to_string(&file).unwrap();
        assert!(!text.contains('@'), "no account in the file");
        std::fs::write(&file, "{not json").unwrap();
        assert_eq!(load(&file), Notified::default());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
