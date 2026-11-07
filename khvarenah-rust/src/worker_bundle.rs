//! Local worker-bundle discovery/validation and preflight diagnostics.

use std::path::{Path, PathBuf};

/// Candidate locations for the edgetunnel _worker.js, searched in order.
fn default_candidates() -> Vec<PathBuf> {
    let home = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default();
    let proj = std::env::current_dir().unwrap_or_default();
    vec![
        proj.join("_worker.js"),
        proj.join("khvarenah").join("_worker.js"),
        home.join("Projects").join("cf-worker-proxy").join("_worker.js"),
        home.join("Projects").join("cf-worker-proxy").join("edgetunnel_worker.js"),
    ]
}

pub fn find_worker_js(explicit: Option<&str>) -> Option<PathBuf> {
    if let Some(e) = explicit {
        let p = PathBuf::from(e).canonicalize().unwrap_or_else(|_| PathBuf::from(e));
        if p.is_file() {
            return Some(p);
        }
        return None;
    }
    for cand in default_candidates() {
        if cand.is_file() {
            return Some(cand);
        }
    }
    None
}

/// Cheap sanity checks (not a full JS parse). Returns (ok, message).
pub fn validate_worker_js(path: &Path) -> (bool, String) {
    let data = match std::fs::read(path) {
        Ok(d) => d,
        Err(e) => return (false, format!("Cannot read worker file: {e}")),
    };
    let blob = String::from_utf8_lossy(&data[..data.len().min(200_000)]).to_lowercase();
    let has_handler = blob.contains("websocket") || blob.contains("upgrade") || blob.contains("fetch");
    if !has_handler {
        return (false, "Worker file does not look like a worker (no fetch/WebSocket handler).".to_string());
    }
    let has_export = blob.contains("export default")
        || blob.contains("export {")
        || blob.contains("addeventlistener");
    if has_export {
        (true, format!("OK — {} bytes, worker layout detected", data.len()))
    } else {
        (false, "Worker file has no export/fetch handler (not a module or service worker).".to_string())
    }
}

/// Generate a random v4 UUID (canonical).
pub fn generate_uuid() -> String {
    uuid::Uuid::new_v4().to_string()
}

/// Sanitize a worker name (lowercase alphanumerics + hyphens, <= 60 chars).
/// Whitespace / underscores become hyphens; other punctuation is dropped.
pub fn safe_worker_name(name: &str) -> String {
    let mut out = String::new();
    for ch in name.trim().to_lowercase().chars() {
        if ch.is_ascii_alphanumeric() || ch == '-' {
            out.push(ch);
        } else if ch == '_' || ch.is_whitespace() {
            out.push('-');
        }
        if out.len() >= 60 {
            break;
        }
    }
    if out.is_empty() {
        "cf-worker".to_string()
    } else {
        let t = out.trim_matches('-').to_string();
        if t.is_empty() { "cf-worker".to_string() } else { t }
    }
}

/// Derive a worker name from an account name.
pub fn worker_name_from_account(account: &serde_json::Value) -> String {
    let name = account
        .get("name")
        .and_then(|n| n.as_str())
        .unwrap_or("cf-worker");
    safe_worker_name(name)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn safe_name_rules() {
        assert_eq!(safe_worker_name("My Worker!"), "my-worker");
        assert_eq!(safe_worker_name("خیر"), "cf-worker");
        assert_eq!(safe_worker_name("---"), "cf-worker");
    }

    #[test]
    fn uuid_is_v4_shape() {
        let u = generate_uuid();
        assert_eq!(u.len(), 36);
        assert_eq!(&u[14..15], "4");
    }
}
