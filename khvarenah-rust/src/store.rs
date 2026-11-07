//! Persistent memory for Khvarenah — **profile-based**.
//!
//! Every piece of durable state (API tokens, generated vless configs, clean
//! IPs, account registry) lives under a *profile*. A user creates as many
//! profiles as they want, and each profile's data is isolated, loadable, and
//! **never cleared** — a software update, redeploy, or config rewrite merges
//! into the existing files, it never resets them.
//!
//! Layout (all JSON, UTF-8, `0o600` for anything holding tokens):
//!
//! ```text
//! ~/.khvarenah/
//!   config.json                  # global: active_profile, version
//!   profiles/<name>/
//!     meta.json                  # name, created_at, updated_at
//!     tokens.json                # account -> token (or "default")
//!     accounts.json              # account_id -> {name, subdomain}
//!     history.json               # generated vless configs
//!     clean-ips.txt              # endpoints found by the clean-IP scanner
//!     clean-configs.txt          # generated working vless links (best first)
//!   profiles/<name>/settings.json# per-profile parameters (defaults overrides)
//! ```

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

const MEM_DIR_NAME: &str = ".khvarenah";

// ---------------------------------------------------------------------------
// Global config
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct GlobalConfig {
    /// The active profile name (empty => "default").
    #[serde(default)]
    pub active_profile: String,
    #[serde(default)]
    pub version: String,
}

// ---------------------------------------------------------------------------
// Profile locations
// ---------------------------------------------------------------------------

fn home() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn mem_dir() -> PathBuf {
    home().join(MEM_DIR_NAME)
}

fn profiles_dir() -> PathBuf {
    mem_dir().join("profiles")
}

fn profile_dir(profile: &str) -> PathBuf {
    let p = if profile.is_empty() { "default".to_string() } else { profile.to_string() };
    profiles_dir().join(p)
}

fn read_global() -> GlobalConfig {
    let p = mem_dir().join("config.json");
    match fs::read_to_string(&p) {
        Ok(s) => serde_json::from_str(&s).unwrap_or_default(),
        Err(_) => GlobalConfig::default(),
    }
}

fn write_global(cfg: &GlobalConfig) -> Result<()> {
    let dir = mem_dir();
    fs::create_dir_all(&dir)?;
    fs::write(
        dir.join("config.json"),
        serde_json::to_string_pretty(cfg)?,
    )?;
    set_perms(&dir.join("config.json"), false)?;
    Ok(())
}

/// The currently-active profile name. Resolution order:
/// 1. `KHVARENAH_PROFILE` env var (explicit override, any command).
/// 2. Global config's `active_profile` (set with `khvarenah profile switch`).
/// 3. "default".
pub fn active_profile() -> String {
    if let Ok(p) = std::env::var("KHVARENAH_PROFILE") {
        let p = p.trim().to_string();
        if !p.is_empty() {
            return p;
        }
    }
    let g = read_global();
    if !g.active_profile.is_empty() {
        g.active_profile
    } else {
        "default".to_string()
    }
}

/// Switch the active profile. Returns an error if it doesn't exist.
pub fn set_active_profile(profile: &str) -> Result<()> {
    if !exists(profile) {
        return Err(anyhow!("profile '{profile}' does not exist"));
    }
    let mut g = read_global();
    g.active_profile = profile.to_string();
    write_global(&g)
}

/// List all profiles (sorted), with creation timestamps.
pub fn list_profiles() -> Result<Vec<ProfileMeta>> {
    let dir = profiles_dir();
    let mut out = Vec::new();
    if !dir.is_dir() {
        return Ok(out);
    }
    for entry in fs::read_dir(&dir)? {
        let entry = entry?;
        let p = entry.path();
        if p.is_dir() {
            if let Some(name) = p.file_name().and_then(|n| n.to_str()) {
                let mut meta = read_meta(&p).unwrap_or_default();
                meta.name = name.to_string();
                out.push(meta);
            }
        }
    }
    out.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(out)
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ProfileMeta {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub created_at: String,
    #[serde(default)]
    pub updated_at: String,
}

pub fn profile_exists(profile: &str) -> bool {
    profile_dir(profile).is_dir()
}

pub fn exists(profile: &str) -> bool {
    profile_exists(profile)
}

fn read_meta(dir: &Path) -> Result<ProfileMeta> {
    let p = dir.join("meta.json");
    if !p.exists() {
        return Ok(ProfileMeta::default());
    }
    let s = fs::read_to_string(&p)?;
    Ok(serde_json::from_str(&s).unwrap_or_default())
}

/// Create a profile (idempotent — does not clear existing data).
pub fn create_profile(profile: &str) -> Result<()> {
    let name = if profile.is_empty() { "default" } else { profile };
    let dir = profile_dir(name);
    fs::create_dir_all(&dir)?;
    set_perms(&dir, true)?;
    let now = now_iso();
    let meta = ProfileMeta {
        name: name.to_string(),
        created_at: now.clone(),
        updated_at: now,
    };
    let meta_path = dir.join("meta.json");
    if !meta_path.exists() {
        fs::write(&meta_path, serde_json::to_string_pretty(&meta)?)?;
    }
    // Ensure the standard per-profile files exist even before first use.
    for f in ["tokens.json", "accounts.json", "history.json", "settings.json"] {
        ensure_json(&dir.join(f))?;
    }
    // If no profile was ever set, make this one active.
    let g = read_global();
    if g.active_profile.is_empty() {
        write_global(&GlobalConfig {
            active_profile: name.to_string(),
            ..g
        })?;
    }
    Ok(())
}

fn ensure_json(path: &Path) -> Result<()> {
    if !path.exists() {
        fs::write(path, "{}")?;
        set_perms(path, true)?;
    }
    Ok(())
}

/// Public timestamp helper (ISO) for building records.
pub fn now_iso() -> String {
    use chrono::Utc;
    Utc::now().format("%Y-%m-%d %H:%M:%S").to_string()
}

/// Public unix-epoch helper.
pub fn now_epoch() -> f64 {
    epoch()
}

fn epoch() -> f64 {
    SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn set_perms(path: &Path, private: bool) -> Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let is_dir = path.metadata().map(|m| m.is_dir()).unwrap_or(false);
        let mode = if is_dir {
            if private { 0o700 } else { 0o755 }
        } else if private {
            0o600
        } else {
            0o644
        };
        fs::set_permissions(path, fs::Permissions::from_mode(mode))?;
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Generic JSON helpers
// ---------------------------------------------------------------------------

fn read_json<T>(path: &Path, default: T) -> T
where
    T: serde::de::DeserializeOwned + Clone,
{
    match fs::read_to_string(path) {
        Ok(s) => serde_json::from_str(&s).unwrap_or(default.clone()),
        Err(_) => default,
    }
}

fn write_json<T>(path: &Path, data: &T, private: bool) -> Result<()>
where
    T: serde::Serialize,
{
    fs::create_dir_all(path.parent().unwrap_or(Path::new(".")))?;
    fs::write(path, serde_json::to_string_pretty(data)?)?;
    set_perms(path, private)?;
    Ok(())
}

fn profile_file(profile: &str, file: &str) -> PathBuf {
    profile_dir(profile).join(file)
}

// ---------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------

/// Per-account token entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenEntry {
    pub token: String,
    #[serde(default)]
    pub ts: String,
}

pub type TokenMap = BTreeMap<String, TokenEntry>;

/// Save a token under a label (profile scoped).
pub fn save_token(profile: &str, token: &str, label: &str) -> Result<()> {
    create_profile(profile)?;
    let path = profile_file(profile, "tokens.json");
    let mut tokens: TokenMap = read_json(&path, TokenMap::new());
    tokens.insert(
        label.to_string(),
        TokenEntry {
            token: token.trim().to_string(),
            ts: now_iso(),
        },
    );
    write_json(&path, &tokens, true)
}

pub fn stored_tokens(profile: &str) -> TokenMap {
    let path = profile_file(profile, "tokens.json");
    read_json(&path, TokenMap::new())
}

#[allow(dead_code)]
pub fn get_token(profile: &str, label: &str) -> Option<String> {
    stored_tokens(profile).get(label).map(|e| e.token.clone())
}

/// Token for an account, falling back to "default".
pub fn get_account_token(profile: &str, account_id: &str) -> Option<String> {
    let t = stored_tokens(profile);
    if !account_id.is_empty() {
        if let Some(e) = t.get(account_id) {
            if !e.token.is_empty() {
                return Some(e.token.clone());
            }
        }
    }
    t.get("default").map(|e| e.token.clone())
}

#[allow(dead_code)]
pub fn clear_tokens(profile: &str) -> Result<()> {
    let path = profile_file(profile, "tokens.json");
    write_json(&path, &TokenMap::new(), true)
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AccountInfo {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub subdomain: String,
}

pub type AccountMap = BTreeMap<String, AccountInfo>;

pub fn remember_account(profile: &str, account_id: &str, name: &str, subdomain: &str) -> Result<()> {
    create_profile(profile)?;
    let path = profile_file(profile, "accounts.json");
    let mut accounts: AccountMap = read_json(&path, AccountMap::new());
    let e = accounts.entry(account_id.to_string()).or_default();
    if !name.is_empty() {
        e.name = name.to_string();
    }
    if !subdomain.is_empty() {
        e.subdomain = subdomain.to_string();
    }
    write_json(&path, &accounts, true)
}

pub fn list_accounts(profile: &str) -> AccountMap {
    let path = profile_file(profile, "accounts.json");
    read_json(&path, AccountMap::new())
}

pub fn account_label(profile: &str, account_id: &str) -> String {
    list_accounts(profile)
        .get(account_id)
        .map(|a| if a.name.is_empty() { account_id.to_string() } else { a.name.clone() })
        .unwrap_or_else(|| account_id.to_string())
}

/// A saved vless config record.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VlessRecord {
    pub id: String,
    pub ts: String,
    pub epoch: f64,
    #[serde(default)]
    pub uuid: String,
    #[serde(default)]
    pub address: String,
    #[serde(default)]
    pub port: u16,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub clean_ip: bool,
    #[serde(default)]
    pub link: String,
    #[serde(default)]
    pub note: String,
}

pub fn remember_vless(profile: &str, rec: &VlessRecord) -> Result<()> {
    create_profile(profile)?;
    let path = profile_file(profile, "history.json");
    let mut history: Vec<VlessRecord> = read_json(&path, Vec::new());
    history.push(rec.clone());
    history.sort_by(|a, b| b.epoch.partial_cmp(&a.epoch).unwrap_or(std::cmp::Ordering::Equal));
    // cap history
    if history.len() > 500 {
        history.truncate(500);
    }
    write_json(&path, &history, false)
}

pub fn list_vless(profile: &str, limit: usize) -> Vec<VlessRecord> {
    let path = profile_file(profile, "history.json");
    let mut v: Vec<VlessRecord> = read_json(&path, Vec::new());
    v.sort_by(|a, b| b.epoch.partial_cmp(&a.epoch).unwrap_or(std::cmp::Ordering::Equal));
    v.truncate(limit);
    v
}

#[allow(dead_code)]
pub fn last_vless(profile: &str, prefer_deployed: bool) -> Option<VlessRecord> {
    let v = list_vless(profile, 200);
    let usable = |r: &VlessRecord| !r.address.is_empty();
    if prefer_deployed {
        if let Some(r) = v.iter().find(|r| !r.clean_ip && usable(r)) {
            return Some(r.clone());
        }
        return v.into_iter().find(usable);
    }
    v.into_iter().find(usable)
}

#[allow(dead_code)]
pub fn clear_history(profile: &str) -> Result<()> {
    let path = profile_file(profile, "history.json");
    write_json(&path, &Vec::<VlessRecord>::new(), false)
}

// ---------------------------------------------------------------------------
// Per-profile settings
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct ProfileSettings {
    pub worker_name: Option<String>,
    pub address: Option<String>,
    pub port: u16,
    pub security: Option<String>,
    pub path: Option<String>,
    pub uuid: Option<String>,
    pub clean_count: u32,
    pub clean_workers: u32,
    pub clean_timeout_s: u32,
    pub clean_top: u32,
    pub clean_ports: String,
    pub clean_gentle: bool,
    pub clean_scan_timeout_s: u32,
    pub auto_find_more: bool,
    /// The account marked active for this profile.
    pub active_account: String,
}

pub fn active_account(profile: &str) -> String {
    settings(profile).active_account
}

pub fn set_active_account(profile: &str, account_id: &str) -> bool {
    let mut s = settings(profile);
    if !account_id.is_empty() && list_accounts(profile).contains_key(account_id) {
        s.active_account = account_id.to_string();
        let _ = save_settings(profile, &s);
        true
    } else {
        false
    }
}

pub fn active_account_for(profile: &str) -> String {
    active_account(profile)
}

pub fn settings(profile: &str) -> ProfileSettings {
    let path = profile_file(profile, "settings.json");
    read_json(&path, ProfileSettings::default())
}

pub fn save_settings(profile: &str, s: &ProfileSettings) -> Result<()> {
    create_profile(profile)?;
    let path = profile_file(profile, "settings.json");
    write_json(&path, s, false)
}

// ---------------------------------------------------------------------------
// Clean IP files
// ---------------------------------------------------------------------------

pub fn clean_ips_file(profile: &str) -> PathBuf {
    profile_file(profile, "clean-ips.txt")
}

pub fn clean_configs_file(profile: &str) -> PathBuf {
    profile_file(profile, "clean-configs.txt")
}

pub fn save_clean_ips(profile: &str, endpoints: &[String]) -> Result<()> {
    create_profile(profile)?;
    fs::write(clean_ips_file(profile), format!("{}\n", endpoints.join("\n")))?;
    Ok(())
}

pub fn save_clean_configs(profile: &str, lines: &[String]) -> Result<()> {
    create_profile(profile)?;
    fs::write(clean_configs_file(profile), format!("{}\n", lines.join("\n")))?;
    Ok(())
}

#[allow(dead_code)]
pub fn load_clean_ips(profile: &str) -> Vec<String> {
    let p = clean_ips_file(profile);
    match fs::read_to_string(&p) {
        Ok(s) => s
            .lines()
            .map(|l| l.trim().to_string())
            .filter(|l| !l.is_empty())
            .collect(),
        Err(_) => Vec::new(),
    }
}

// ---------------------------------------------------------------------------
// Convenience
// ---------------------------------------------------------------------------

pub fn memory_summary(profile: &str) -> String {
    let hv = list_vless(profile, 3);
    let tok = stored_tokens(profile);
    let accs = list_accounts(profile);
    let mut lines: Vec<String> = Vec::new();
    let p = active_profile();
    lines.push(format!("📂 profile: {p}"));
    if !hv.is_empty() {
        lines.push(format!("🧠 {} saved vless config(s)", hv.len()));
        for r in &hv {
            let tag = if r.clean_ip { "clean-IP" } else { "workers.dev" };
            lines.push(format!("   • {} [{}] {}", r.name, tag, r.ts));
        }
    }
    if !tok.is_empty() {
        lines.push(format!("🔑 {} saved token(s)", tok.len()));
    }
    if !accs.is_empty() {
        lines.push(format!("☁️ {} saved account(s)", accs.len()));
    }
    if lines.len() == 1 {
        lines.push("No saved configs yet.".to_string());
    }
    lines.join("\n")
}

pub fn ensure_profile(profile: &str) -> Result<()> {
    create_profile(profile)
}

/// The absolute path of the profile directory (for user-facing messages).
pub fn profile_dir_path(profile: &str) -> PathBuf {
    profile_dir(profile)
}

/// Delete a profile (recursively). Refuses to delete the active one unless
/// `force` is set (then falls back to "default").
pub fn delete_profile(profile: &str) -> Result<()> {
    let dir = profile_dir(profile);
    if !dir.exists() {
        return Err(anyhow!("profile '{profile}' does not exist"));
    }
    if active_profile() == profile {
        let mut g = read_global();
        g.active_profile = "default".to_string();
        write_global(&g)?;
    }
    fs::remove_dir_all(&dir).with_context(|| format!("failed to delete profile dir {dir:?}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// All store tests mutate the process-global HOME env var, so they must be
    /// serialized or they race each other.
    static TEST_LOCK: once_cell::sync::Lazy<std::sync::Mutex<()>> =
        once_cell::sync::Lazy::new(|| std::sync::Mutex::new(()));

    fn test_dir(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("khv-test-{tag}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        // Override HOME so the store is isolated per test.
        d
    }

    fn with_home(tag: &str, f: impl FnOnce() -> Result<()>) {
        let _guard = TEST_LOCK.lock().unwrap();
        let d = test_dir(tag);
        std::env::set_var("HOME", &d);
        let r = f();
        std::env::remove_var("HOME");
        let _ = fs::remove_dir_all(&d);
        r.unwrap();
    }

    #[test]
    fn profiles_are_isolated_and_never_cleared() {
        with_home("iso", || {
            create_profile("work")?;
            create_profile("home")?;
            save_token("work", "TOKEN_A", "default")?;
            save_token("home", "TOKEN_B", "default")?;
            assert_eq!(get_token("work", "default").as_deref(), Some("TOKEN_A"));
            assert_eq!(get_token("home", "default").as_deref(), Some("TOKEN_B"));
            // Re-create (simulating an update) must NOT clear data.
            create_profile("work")?;
            assert_eq!(get_token("work", "default").as_deref(), Some("TOKEN_A"));
            Ok(())
        });
    }

    #[test]
    fn save_token_merges_into_existing() {
        with_home("merge", || {
            create_profile("p")?;
            save_token("p", "T1", "default")?;
            save_token("p", "T2", "acct2")?;
            let t = stored_tokens("p");
            assert_eq!(t.len(), 2);
            assert_eq!(t["default"].token, "T1");
            assert_eq!(t["acct2"].token, "T2");
            Ok(())
        });
    }

    #[test]
    fn history_sorted_newest_first() {
        with_home("hist", || {
            create_profile("p")?;
            for i in 0..3 {
                remember_vless(
                    "p",
                    &VlessRecord {
                        id: i.to_string(),
                        ts: now_iso(),
                        epoch: epoch() + i as f64,
                        uuid: "".into(),
                        address: format!("h{i}.workers.dev"),
                        port: 443,
                        name: format!("n{i}"),
                        clean_ip: false,
                        link: "".into(),
                        note: "".into(),
                    },
                )?;
            }
            let v = list_vless("p", 10);
            assert_eq!(v[0].address, "h2.workers.dev");
            assert_eq!(v[2].address, "h0.workers.dev");
            Ok(())
        });
    }

    #[test]
    fn active_profile_falls_back_to_default() {
        with_home("active", || {
            assert_eq!(active_profile(), "default");
            create_profile("work")?;
            set_active_profile("work")?;
            assert_eq!(active_profile(), "work");
            Ok(())
        });
    }
}
