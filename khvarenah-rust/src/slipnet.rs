//! SlipNet integration — advanced DNS-resolver scanning tool.
//!
//! SlipNet (https://github.com/anonvector/SlipNet) is a DNS-tunneling VPN
//! client. Its CLI ships a built-in scanner that probes DNS resolvers for
//! tunnel compatibility (EDNS probing, NXDOMAIN hijacking detection, latency
//! scoring) and can restrict scans to a country's IP ranges (Iran, Russia,
//! China and more).
//!
//! This is *not* the clean-IP scanner used by autopilot (which targets
//! Cloudflare / edgetunnel worker endpoints). It is an **advanced tool**: a
//! user who runs their own SlipGate DNS-tunnel server can use it to find the
//! best DNS resolvers for their region.

use anyhow::{anyhow, Result};
use std::fs;
use std::path::PathBuf;
use std::process::Command;

/// SlipNet CLI release we vendor by default (first tag that shipped Linux CLI
/// binaries; newer tags only ship APKs).
pub const CLL_RELEASE: &str = "v2.5.3";

pub const COUNTRIES: &[(&str, &str)] = &[
    ("ir", "Iran"),
    ("ru", "Russia"),
    ("cn", "China"),
    ("us", "United States"),
    ("de", "Germany"),
    ("tr", "Turkey"),
];

pub fn bin_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".khvarenah")
        .join("bin")
}

pub fn bin_path() -> PathBuf {
    bin_dir().join("slipnet")
}

fn platform_asset() -> &'static str {
    let os = std::env::consts::OS;
    let arch = std::env::consts::ARCH;
    match (os, arch) {
        ("linux", "aarch64") => "slipnet-linux-arm64",
        ("linux", "arm") => "slipnet-linux-armv7",
        ("macos", "aarch64") => "slipnet-darwin-arm64",
        ("macos", _) => "slipnet-darwin-amd64",
        ("windows", _) => "slipnet-windows-amd64.exe",
        _ => "slipnet-linux-amd64",
    }
}

/// Download the SlipNet CLI binary for this platform.
pub fn install() -> Result<String> {
    let dir = bin_dir();
    fs::create_dir_all(&dir)?;
    let asset = platform_asset();
    let url = format!(
        "https://github.com/anonvector/SlipNet/releases/download/{CLL_RELEASE}/{asset}"
    );
    let tmp = dir.join(format!("{asset}.part"));
    let bytes = reqwest::blocking::get(&url)?.bytes()?;
    fs::write(&tmp, bytes)?;
    let bin = bin_path();
    fs::rename(&tmp, &bin)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&bin, fs::Permissions::from_mode(0o755))?;
    }
    Ok(format!("Installed SlipNet CLI → {}", bin.display()))
}

pub fn ensure_installed() -> Result<PathBuf> {
    let bin = bin_path();
    if bin.exists() {
        Ok(bin)
    } else {
        install()?;
        Ok(bin)
    }
}

/// Country → IP-range scan: SlipNet's built-in country lists.
pub fn country_range(country: &str) -> Option<&'static str> {
    COUNTRIES
        .iter()
        .find(|(c, _)| *c == country)
        .map(|(_, name)| *name)
}

/// Run a SlipNet DNS scan.
///
/// `domain` is the DNS-tunnel zone (e.g. `t.example.com`), `country` restricts
/// to a country's resolver ranges, `ips_file` scans a custom resolver list.
pub fn dns_scan(domain: &str, region: &str, ips_file: Option<&str>) -> Result<String> {
    let bin = ensure_installed()?;
    let mut cmd = Command::new(&bin);
    cmd.arg("scan").arg("--domain").arg(domain);

    if let Some(f) = ips_file {
        cmd.arg("--ips").arg(f);
    } else if !region.is_empty() {
        cmd.arg("--country").arg(region);
    }

    let output = cmd.output().map_err(|e| anyhow!("failed to run slipnet: {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    if !output.status.success() {
        return Err(anyhow!("slipnet scan failed:\n{stdout}\n{stderr}"));
    }
    Ok(stdout)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn country_list_contains_iran() {
        assert_eq!(country_range("ir"), Some("Iran"));
        assert_eq!(country_range("ru"), Some("Russia"));
        assert_eq!(country_range("cn"), Some("China"));
        assert_eq!(country_range("xx"), None);
    }

    #[test]
    fn platform_asset_never_empty() {
        assert!(!platform_asset().is_empty());
    }
}
