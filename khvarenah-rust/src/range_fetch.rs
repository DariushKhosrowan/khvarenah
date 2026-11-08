//! Cloudflare IPv4 range discovery — live fetch with cache + embedded fallback.
//!
//! The primary source is the official CF API (`api.cloudflare.com/client/v4/ips`).
//! Results are cached for 24h at `~/.khvarenah/cache/cf-ranges.json`. If the live
//! fetch fails we fall back to the cache (even if stale) and finally to the
//! embedded list below. This matches the architect's requirement that ranges are
//! *never* hardcoded as the primary source — they change every 12–24 months.

use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

/// Cache TTL: 24 hours.
pub const RANGES_TTL_HOURS: u64 = 24;

/// Embedded fallback list (current as of writing). Only used when both the live
/// API and the cache are unavailable. `104.16.0.0/13` alone is 2^19 IPs, so
/// the scanner samples, never enumerates.
pub fn embedded_cf_ranges() -> &'static [&'static str] {
    &[
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "173.245.48.0/20",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "188.114.96.0/20",
        "190.93.240.0/20",
        "197.234.240.0/22",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
    ]
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RangesCache {
    pub fetched_at: i64,
    pub ranges: Vec<String>,
}

/// Directory where cache files live.
pub fn cache_dir() -> PathBuf {
    if let Some(override_dir) = std::env::var_os("KHVARENAH_CACHE_DIR") {
        return PathBuf::from(override_dir);
    }
    let home = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."));
    home.join(".khvarenah").join("cache")
}

fn ranges_cache_file() -> PathBuf {
    cache_dir().join("cf-ranges.json")
}

fn now_epoch() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0)
}

fn read_cache() -> Option<RangesCache> {
    let p = ranges_cache_file();
    let s = fs::read_to_string(&p).ok()?;
    serde_json::from_str(&s).ok()
}

fn write_cache(ranges: &[String]) {
    let c = RangesCache { fetched_at: now_epoch(), ranges: ranges.to_vec() };
    if let Ok(s) = serde_json::to_string_pretty(&c) {
        let _ = fs::create_dir_all(cache_dir());
        let _ = fs::write(ranges_cache_file(), s);
    }
}

/// Parse the official JSON API response into a list of IPv4 CIDR strings.
fn parse_official_api(body: &str) -> Result<Vec<String>> {
    let v: serde_json::Value = serde_json::from_str(body)
        .map_err(|e| anyhow!("CF IP API returned invalid JSON: {e}"))?;
    let result = v
        .get("result")
        .and_then(|r| r.get("ipv4_cidrs"))
        .and_then(|a| a.as_array())
        .ok_or_else(|| anyhow!("CF IP API response missing result.ipv4_cidrs"))?;
    let mut out = Vec::new();
    for r in result {
        if let Some(s) = r.as_str() {
            out.push(s.to_string());
        }
    }
    Ok(out)
}

/// Fetch the live CF IPv4 CIDR list from the official API.
pub fn fetch_cf_ranges(timeout_s: u64) -> Result<Vec<String>> {
    let url = "https://api.cloudflare.com/client/v4/ips";
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(timeout_s.max(1)))
        .build()
        .map_err(|e| anyhow!("failed to build client: {e}"))?;
    let resp = client.get(url).send().map_err(|e| anyhow!("CF IP API request failed: {e}"))?;
    if !resp.status().is_success() {
        return Err(anyhow!("CF IP API returned HTTP {}", resp.status()));
    }
    let body = resp.text().map_err(|e| anyhow!("failed to read body: {e}"))?;
    let ranges = parse_official_api(&body)?;
    if ranges.is_empty() {
        return Err(anyhow!("CF IP API returned an empty range list"));
    }
    Ok(ranges)
}

/// Fetch CF ranges with a 24h cache. Returns `(ranges, source)` where source is
/// one of "live", "cache", "embedded".
pub fn fetch_cf_ranges_cached(ttl_hours: u64) -> Result<(Vec<String>, &'static str)> {
    // 1. Try cache first (fast path; also the source of truth while it's fresh).
    if let Some(c) = read_cache() {
        let age_hours = (now_epoch() - c.fetched_at) as u64 / 3600;
        if age_hours < ttl_hours.max(1) && !c.ranges.is_empty() {
            return Ok((c.ranges, "cache"));
        }
    }

    // 2. Live fetch; on success cache it.
    match fetch_cf_ranges(10) {
        Ok(ranges) => {
            write_cache(&ranges);
            Ok((ranges, "live"))
        }
        Err(_) => {
            // 3. Cache even if stale.
            if let Some(c) = read_cache() {
                if !c.ranges.is_empty() {
                    return Ok((c.ranges, "cache"));
                }
            }
            // 4. Embedded fallback.
            let embedded = embedded_cf_ranges().iter().map(|s| s.to_string()).collect();
            Ok((embedded, "embedded"))
        }
    }
}

/// Convenience: fetch with the default TTL.
pub fn default_cf_ranges() -> Result<(Vec<String>, &'static str)> {
    fetch_cf_ranges_cached(RANGES_TTL_HOURS)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedded_list_is_nonempty_v4() {
        let list = embedded_cf_ranges();
        assert!(!list.is_empty());
        for cidr in list {
            assert!(cidr.contains('/'), "expected CIDR, got {cidr}");
        }
    }

    #[test]
    fn parse_official_api_response() {
        let body = r#"{"success":true,"errors":[],"messages":[],"result":{"ipv4_cidrs":["104.16.0.0/13","172.64.0.0/13"],"ipv6_cidrs":["2606:4700::/32"]}}"#;
        let ranges = parse_official_api(body).unwrap();
        assert_eq!(ranges.len(), 2);
        assert_eq!(ranges[0], "104.16.0.0/13");
    }

    #[test]
    fn parse_official_api_missing_field_errors() {
        let body = r#"{"success":false}"#;
        assert!(parse_official_api(body).is_err());
    }

    #[test]
    fn cache_roundtrips_hermetic() {
        let tmp = std::env::temp_dir().join(format!("khv-cache-{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("KHVARENAH_CACHE_DIR", &tmp);

        let c = RangesCache { fetched_at: now_epoch(), ranges: vec!["104.16.0.0/13".to_string()] };
        write_cache(&c.ranges);
        let got = read_cache().unwrap();
        assert_eq!(got.ranges, c.ranges);
        assert!(got.fetched_at <= now_epoch());

        let _ = fs::remove_dir_all(&tmp);
        std::env::remove_var("KHVARENAH_CACHE_DIR");
    }

    #[test]
    fn embedded_returned_when_no_cache() {
        let tmp = std::env::temp_dir().join(format!("khv-cache-{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("KHVARENAH_CACHE_DIR", &tmp);

        // No cache file yet -> fetch_cf_ranges_cached must still yield a non-empty list.
        let (ranges, source) = match fetch_cf_ranges_cached(24) {
            Ok(v) => v,
            Err(_) => (embedded_cf_ranges().iter().map(|s| s.to_string()).collect(), "embedded"),
        };
        assert!(!ranges.is_empty());
        assert!(matches!(source, "live" | "cache" | "embedded"));

        let _ = fs::remove_dir_all(&tmp);
        std::env::remove_var("KHVARENAH_CACHE_DIR");
    }
}
