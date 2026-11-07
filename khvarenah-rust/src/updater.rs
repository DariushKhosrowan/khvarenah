//! Version reporting + self-update from GitHub releases.
//!
//! The update *merges* into the existing profile store — it never clears
//! tokens/configs/history (see store.rs).

use anyhow::Result;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
pub const REPO: &str = "DariushKhosrowan/khvarenah";

#[allow(dead_code)]
pub fn current_version() -> &'static str {
    VERSION
}

/// Check the latest GitHub release tag for the project. Returns Err on
/// network/lookup failure (not fatal).
pub fn latest_release_tag() -> Result<String> {
    let url = format!("https://api.github.com/repos/{REPO}/releases/latest");
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .user_agent("khvarenah-updater")
        .build()?;
    let resp = client.get(&url).send()?;
    if !resp.status().is_success() {
        return Err(anyhow::anyhow!("GitHub API returned {}", resp.status()));
    }
    let v: serde_json::Value = resp.json()?;
    let tag = v
        .get("tag_name")
        .and_then(|t| t.as_str())
        .unwrap_or("")
        .to_string();
    if tag.is_empty() {
        return Err(anyhow::anyhow!("No tag in release payload"));
    }
    Ok(tag)
}

/// Compare a `vX.Y.Z` tag to the current package version.
pub fn is_newer(tag: &str) -> bool {
    let tag = tag.trim_start_matches('v');
    let parse = |s: &str| -> (u64, u64, u64) {
        let mut parts = s.split('.').map(|p| p.parse::<u64>().unwrap_or(0));
        (
            parts.next().unwrap_or(0),
            parts.next().unwrap_or(0),
            parts.next().unwrap_or(0),
        )
    };
    let (a, b, c) = parse(tag);
    let (x, y, z) = parse(VERSION);
    (a, b, c) > (x, y, z)
}

/// Check for an update. Returns (available, message).
pub fn check_for_update() -> Result<(bool, String)> {
    match latest_release_tag() {
        Ok(tag) => {
            if is_newer(&tag) {
                Ok((true, format!("Update available: {tag} (local {VERSION})")))
            } else {
                Ok((false, format!("Already up to date ({VERSION}).")))
            }
        }
        Err(e) => Ok((false, format!("Could not check for updates: {e}"))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_compare() {
        assert!(is_newer("v0.3.0"));
        assert!(is_newer("v0.2.1"));
        assert!(!is_newer("v0.1.0"));
        assert!(!is_newer("v0.2.0"));
        assert!(!is_newer("v0.1.9"));
    }
}
