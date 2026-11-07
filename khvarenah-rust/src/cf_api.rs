//! Cloudflare Workers API client with human-friendly error classification.

use anyhow::Result;
use serde_json::Value;
use std::collections::BTreeMap;

use crate::stealth::{pre_request_pause, retry_backoff};

pub const API: &str = "https://api.cloudflare.com/client/v4";
pub const DEFAULT_COMPAT_DATE: &str = "2026-07-01";

/// A structured, human-readable error with a suggested fix.
#[derive(Debug, Clone)]
pub struct CfError {
    pub title: String,
    pub detail: String,
    #[allow(dead_code)]
    pub fix: String,
    pub status: Option<u16>,
    #[allow(dead_code)]
    pub code: Option<i64>,
}

impl std::fmt::Display for CfError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.title, self.detail)
    }
}

impl std::error::Error for CfError {}

impl CfError {
    pub fn new(title: impl Into<String>, detail: impl Into<String>, fix: impl Into<String>) -> Self {
        Self {
            title: title.into(),
            detail: detail.into(),
            fix: fix.into(),
            status: None,
            code: None,
        }
    }
}

/// Map well-known Cloudflare error codes to (title, fix).
fn known_code(code: i64) -> Option<(&'static str, &'static str)> {
    let m: BTreeMap<i64, (&str, &str)> = [
        (10000, ("Authentication failure", "The API token was rejected. Re-enter it (or create a new one in the Cloudflare dashboard).")),
        (9109, ("Invalid API token", "The token is malformed or empty. Paste a full token from Cloudflare → My Profile → API Tokens.")),
        (6003, ("Insufficient permission", "The token lacks a required permission. Recreate it with at least: Account-Settings-Read, Workers-Scripts-Edit, Workers-KV-Storage-Edit, Workers-Scripts-Read.")),
        (10021, ("Too many requests", "You hit a rate limit. Wait ~30s and retry.")),
        (10022, ("Not authenticated", "Token missing/expired. Re-authenticate.")),
        (9106, ("Script deleted", "This worker was deleted in the dashboard.")),
        (8000001, ("Worker script error", "The uploaded script failed to parse/validate. Check that the worker JS is the correct edgetunnel module file.")),
    ]
    .into_iter()
    .collect();
    m.get(&code).copied()
}

fn classify_status(status: u16) -> Option<(&'static str, &'static str)> {
    match status {
        400 => Some(("Bad request", "One of the fields is invalid. Verify the worker name (lowercase letters, numbers, hyphens) and re-check the script.")),
        401 => Some(("Not authenticated", "The API token is invalid or expired. Get a fresh token from Cloudflare → My Profile → API Tokens.")),
        403 => Some(("Permission denied", "The token is missing a required permission. Recreate it with Workers-Scripts-Edit & Account-Settings-Read (see the 'Create Token' guidance in the console).")),
        404 => Some(("Not found", "Check the Account ID and that the worker name is correct. The account may not be accessible with this token.")),
        409 => Some(("Conflict", "A resource with this name already exists in a conflicting state. Pick another worker name or delete the existing one.")),
        413 => Some(("Script too large", "The worker bundle is over the size limit. Use the standard edgetunnel worker file.")),
        429 => Some(("Rate limited", "Slow down — wait a few seconds and retry. Free-tier limits apply.")),
        _ if status >= 500 => Some(("Cloudflare-side error", "This is a Cloudflare outage/5xx. Wait briefly and retry.")),
        _ => None,
    }
}

/// Build a CfError from a non-2xx Cloudflare response body.
fn explain_response(status: u16, body: &Value, fallback: &str) -> CfError {
    // Pull an error code / message out of the CF envelope.
    let mut code = None;
    let mut detail = String::new();
    if let Some(errs) = body.get("errors").and_then(|e| e.as_array()) {
        if let Some(e0) = errs.first() {
            code = e0.get("code").and_then(|c| c.as_i64());
            detail = e0
                .get("message")
                .and_then(|m| m.as_str())
                .unwrap_or("")
                .to_string();
        }
    }
    if detail.is_empty() {
        detail = body
            .get("errors")
            .or_else(|| body.get("messages"))
            .and_then(|v| v.as_str())
            .unwrap_or(fallback)
            .to_string();
    }

    let (title, fix) = if let Some(c) = code {
        if let Some(k) = known_code(c) {
            k
        } else if let Some(k) = classify_status(status) {
            k
        } else {
            ("Request failed", "Review the raw error below and adjust accordingly.")
        }
    } else if let Some(k) = classify_status(status) {
        k
    } else {
        ("Request failed", "Review the raw error below and adjust accordingly.")
    };

    CfError {
        title: title.to_string(),
        detail,
        fix: fix.to_string(),
        status: Some(status),
        code,
    }
}

/// Client wrapper. All network calls are plain blocking requests (slow but
/// portable); the CLI runs them on the current thread.
#[derive(Debug, Clone)]
pub struct Config {
    pub token: String,
    pub timeout: u64,
}

impl Config {
    pub fn new(token: &str) -> Self {
        Self {
            token: token.trim().to_string(),
            timeout: 25,
        }
    }

    #[allow(dead_code)]
    pub fn with_timeout(mut self, timeout: u64) -> Self {
        self.timeout = timeout;
        self
    }

    /// Execute a request, mapping network/TLS errors to CfError.
    fn request(&self, method: &str, path: &str, body: Option<Value>, files: Option<&[(&str, Vec<u8>)]>, _action: &str, timeout: Option<u64>) -> Result<Value, CfError> {
        let eff_to = timeout.unwrap_or(self.timeout);
        let is_write = method == "PUT" || method == "PATCH" || method == "DELETE" || files.is_some();
        pre_request_pause(if is_write { "write" } else { "read" });

        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(eff_to))
            .build()
            .map_err(|e| CfError::new("Client build error", e.to_string(), ""))?;

        let url = format!("{API}{path}");
        let mut req = client
            .request(
                reqwest::Method::from_bytes(method.as_bytes()).map_err(|e| {
                    CfError::new("Bad method", e.to_string(), "")
                })?,
                &url,
            )
            .header("Authorization", format!("Bearer {}", self.token));

        if let Some(files) = files {
            // multipart upload (e.g. deploying a worker script)
            let mut form = reqwest::blocking::multipart::Form::new();
            for (name, bytes) in files {
                let mime = if *name == "_worker.js" {
                    "application/javascript"
                } else {
                    "application/octet-stream"
                };
                form = form.part(
                    name.to_string(),
                    reqwest::blocking::multipart::Part::bytes(bytes.to_vec())
                        .mime_str(mime)
                        .expect("valid mime"),
                );
            }
            // merge JSON parts (e.g. metadata) with application/json content type
            if let Some(obj) = body.and_then(|b| b.as_object().cloned()) {
                for (k, v) in obj {
                    form = form.part(
                        k.clone(),
                        reqwest::blocking::multipart::Part::text(v.to_string())
                            .mime_str("application/json")
                            .expect("valid mime"),
                    );
                }
            }
            req = req.multipart(form);
        } else if let Some(b) = body {
            req = req.json(&b);
        }

        let resp = match req.send() {
            Ok(r) => r,
            Err(e) => {
                let e_str = e.to_string();
                if e_str.contains("dns") || e_str.contains("Connection") || e_str.contains("tcp") {
                    return Err(CfError::new(
                        "Network error",
                        format!("Could not reach {API}. ({e_str})"),
                        "Are you offline? Cloudflare may be blocked/filtered where you are — the console still works for generating configs and local testing.",
                    ));
                }
                if e_str.contains("tls") || e_str.contains("ssl") {
                    return Err(CfError::new(
                        "TLS error",
                        "Could not establish a secure connection to Cloudflare.",
                        "Check your network / proxy settings.",
                    ));
                }
                if e.is_timeout() {
                    return Err(CfError::new(
                        "Timeout",
                        format!("No response from Cloudflare after {eff_to}s."),
                        "Retry; if it persists, the API may be blocked on your network.",
                    ));
                }
                return Err(CfError::new("Unexpected error", e_str, "Review the error and try again."));
            }
        };

        let status = resp.status().as_u16();
        let body_val: Value = resp.json().unwrap_or(Value::Null);

        if (200..300).contains(&status) {
            return Ok(body_val);
        }
        Err(explain_response(status, &body_val, "request failed"))
    }

    // -- auth / account ---------------------------------------------------

    pub fn verify_token(&self) -> Result<Value, CfError> {
        self.request("GET", "/user/tokens/verify", None, None, "verify token", None)
    }

    pub fn list_accounts(&self) -> Result<Vec<Value>, CfError> {
        let v = self.request("GET", "/accounts?per_page=100", None, None, "list accounts", None)?;
        Ok(v.get("result").and_then(|r| r.as_array()).cloned().unwrap_or_default())
    }

    pub fn get_subdomain(&self, account_id: &str) -> Result<String, CfError> {
        let path = format!("/accounts/{account_id}/workers/subdomain");
        let v = self.request("GET", &path, None, None, "get workers subdomain", None)?;
        Ok(v.get("result").and_then(|r| r.get("subdomain")).and_then(|s| s.as_str()).unwrap_or("").to_string())
    }

    // -- scripts -----------------------------------------------------------

    pub fn list_scripts(&self, account_id: &str) -> Result<Vec<Value>, CfError> {
        let path = format!("/accounts/{account_id}/workers/scripts?per_page=50");
        let v = self.request("GET", &path, None, None, "list scripts", None)?;
        Ok(v.get("result").and_then(|r| r.as_array()).cloned().unwrap_or_default())
    }

    pub fn script_analytics(&self, account_id: &str, name: &str, since: &str, until: &str) -> Result<Value, CfError> {
        let path = format!("/accounts/{account_id}/workers/scripts/{name}/analytics/summary?since={since}&until={until}");
        let v = self.request("GET", &path, None, None, "get worker analytics", None)?;
        Ok(v.get("result").cloned().unwrap_or(Value::Null))
    }

    pub fn deploy_script(&self, account_id: &str, name: &str, js: &[u8], compat_date: &str, retries: u32) -> Result<Value, CfError> {
        let mut last: Option<CfError> = None;
        for attempt in 0..=retries {
            match self.deploy_once(account_id, name, js, compat_date) {
                Ok(v) => return Ok(v),
                Err(e) => {
                    last = Some(e.clone());
                    let retry = e.status.map(|s| s == 429 || s >= 500).unwrap_or(false);
                    if !retry || attempt == retries {
                        return Err(e);
                    }
                    retry_backoff(attempt);
                }
            }
        }
        Err(last.unwrap_or_else(|| CfError::new("Deploy failed", "unknown", "")))
    }

    fn deploy_once(&self, account_id: &str, name: &str, js: &[u8], compat_date: &str) -> Result<Value, CfError> {
        let metadata = serde_json::json!({
            "main_module": "_worker.js",
            "compatibility_date": compat_date,
            "compatibility_flags": ["nodejs_compat"]
        });
        let path = format!("/accounts/{account_id}/workers/scripts/{name}");
        // multipart: metadata (text part) + _worker.js (file part)
        let body = serde_json::json!({ "metadata": metadata.to_string() });
        self.request("PUT", &path, Some(body), Some(&[("_worker.js", js.to_vec())]), "deploy worker", Some(120))
    }

    #[allow(dead_code)]
    pub fn set_vars(&self, account_id: &str, name: &str, vars: &serde_json::Map<String, Value>) -> Result<Value, CfError> {
        let path = format!("/accounts/{account_id}/workers/scripts/{name}/settings");
        let body = serde_json::json!({ "vars": vars });
        self.request("PATCH", &path, Some(body), None, "set worker vars", None)
    }

    #[allow(dead_code)]
    pub fn delete_script(&self, account_id: &str, name: &str) -> Result<Value, CfError> {
        let path = format!("/accounts/{account_id}/workers/scripts/{name}");
        self.request("DELETE", &path, None, None, "delete worker", None)
    }

    // -- derived helpers ---------------------------------------------------

    pub fn account_display(&self, account: &Value) -> String {
        let name = account.get("name").and_then(|n| n.as_str()).unwrap_or("");
        let id = account.get("id").and_then(|i| i.as_str()).unwrap_or("");
        format!("{name} ({id})")
    }

    #[allow(dead_code)]
    pub fn workers_dev_url(&self, account_id: &str, name: &str) -> Result<String, CfError> {
        let sub = self.get_subdomain(account_id)?;
        Ok(format!("https://{name}.{sub}.workers.dev"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classify_known_code() {
        let (title, _) = known_code(10000).unwrap();
        assert_eq!(title, "Authentication failure");
    }

    #[test]
    fn classify_401() {
        let (title, _) = classify_status(401).unwrap();
        assert_eq!(title, "Not authenticated");
    }

    #[test]
    fn explain_uses_envelope_code() {
        let body = serde_json::json!({
            "errors": [{ "code": 9109, "message": "bad token" }]
        });
        let e = explain_response(400, &body, "");
        assert_eq!(e.title, "Invalid API token");
        assert_eq!(e.code, Some(9109));
    }
}
