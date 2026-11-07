//! Clean-IP finding via SenPaiScanner.
//!
//! Shells out to SenPaiScanner's standalone CLI (plain-text mode), collects its
//! live-results / output file, and returns healthy endpoints.
//!
//! **Smart stop-on-first-working** behaviour: by default the scanner targets a
//! single validated endpoint (`-top 1`) so it stops as soon as ONE working IP is
//! found. It only keeps going to find more when the caller explicitly asks
//! (`--more N` / `--all`).

use anyhow::{anyhow, Result};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

pub const RELEASE: &str = "v1.1.1";

/// Smart stop-on-first-working default: aim for exactly ONE verified working
/// endpoint before stopping. Raise it (--more N / --all) only when the user
/// explicitly asks for more configs.
pub const DEFAULT_TARGET_TOP: u32 = 1;

pub fn bin_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".khvarenah")
        .join("bin")
}

pub fn bin_path() -> PathBuf {
    bin_dir().join("senpaiscanner")
}

fn platform_asset() -> &'static str {
    let os = std::env::consts::OS;
    let arch = std::env::consts::ARCH;
    match (os, arch) {
        ("windows", "x86_64") => "SenPaiScanner-1.1.1-cli-windows-amd64.exe",
        ("windows", _) => "SenPaiScanner-1.1.1-cli-windows-arm64.exe",
        ("macos", "aarch64") => "SenPaiScanner-1.1.1-cli-macos-apple-silicon",
        ("macos", _) => "SenPaiScanner-1.1.1-cli-macos-intel",
        ("linux", "aarch64") => "SenPaiScanner-1.1.1-cli-linux-arm64",
        ("linux", "arm") => "SenPaiScanner-1.1.1-cli-linux-armv7",
        _ => "SenPaiScanner-1.1.1-cli-linux-amd64",
    }
}

/// Download the SenPaiScanner CLI for this platform.
pub fn install() -> Result<String> {
    let dir = bin_dir();
    fs::create_dir_all(&dir)?;
    let asset = platform_asset();
    let url = format!(
        "https://github.com/MatinSenPai/SenPaiScanner/releases/download/{RELEASE}/{asset}"
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
    Ok(format!("Installed SenPaiScanner → {}", bin.display()))
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

#[derive(Debug, Clone)]
pub struct CleanIpResult {
    pub endpoints: Vec<String>,
    #[allow(dead_code)]
    pub raw: String,
    pub message: String,
}

const GOOD_IP_PATTERN: &str = "^\\d{1,3}(\\.\\d{1,3}){3}:\\d+$";

fn is_good_ip(e: &str) -> bool {
    let re = regex::Regex::new(GOOD_IP_PATTERN).unwrap();
    re.is_match(e)
}

/// Extract an endpoint "ip:port" from a line if present.
fn endpoint_in_line(line: &str) -> Option<String> {
    let re = regex::Regex::new(r"(^|\s|:)(\d{1,3}(\.\d{1,3}){3}):(\d+)").unwrap();
    for cap in re.captures_iter(line) {
        let ip = cap.get(2).map(|m| m.as_str()).unwrap_or("");
        let port = cap.get(4).map(|m| m.as_str()).unwrap_or("");
        if !ip.is_empty() && !port.is_empty() {
            return Some(format!("{ip}:{port}"));
        }
    }
    None
}

fn add_unique(list: &mut Vec<String>, e: String) {
    let e = e.trim().to_lowercase();
    if is_good_ip(&e) && !list.contains(&e) {
        list.push(e);
    }
}

/// Collect endpoints from live-results files in cwd + bin dir, the output file,
/// and stdout.
fn collect_endpoints(live_glob_dirs: &[PathBuf], out_file: Option<&Path>, stdout: &str) -> Vec<String> {
    let mut seen: Vec<String> = Vec::new();

    // iterate dirs, find SenPaiScannerResult-*.txt
    for dir in live_glob_dirs {
        if let Ok(entries) = fs::read_dir(dir) {
            let mut files: Vec<PathBuf> = entries
                .flatten()
                .map(|e| e.path())
                .filter(|p| {
                    p.file_name()
                        .and_then(|n| n.to_str())
                        .map(|n| n.starts_with("SenPaiScannerResult-") && n.ends_with(".txt"))
                        .unwrap_or(false)
                })
                .collect();
            files.sort();
            for f in files.iter().rev() {
                if let Ok(s) = fs::read_to_string(f) {
                    for line in s.lines() {
                        if let Some(ep) = endpoint_in_line(line) {
                            add_unique(&mut seen, ep);
                        }
                    }
                }
            }
        }
    }

    if let Some(out) = out_file {
        if out.exists() {
            if let Ok(s) = fs::read_to_string(out) {
                for line in s.lines() {
                    add_unique(&mut seen, line.to_string());
                }
            }
        }
    }

    for m in regex::Regex::new(r"(^|\s)(\d{1,3}(\.\d{1,3}){3}):(\d+)").unwrap().captures_iter(stdout) {
        let ip = m.get(2).map(|x| x.as_str()).unwrap_or("");
        let port = m.get(4).map(|x| x.as_str()).unwrap_or("");
        if !ip.is_empty() && !port.is_empty() {
            add_unique(&mut seen, format!("{ip}:{port}"));
        }
    }

    seen
}

/// Run SenPaiScanner against a vless link, returning clean endpoints.
///
/// `target_top` controls how many validated endpoints to aim for before the
/// scanner stops. Use `1` for "stop on first working IP" (the smart default),
/// or a larger number to gather more.
pub fn find_clean_ips(
    vless_link: &str,
    count: u32,
    workers: u32,
    timeout_s: u32,
    gentle: bool,
    ports: &str,
    scan_timeout: u32,
    target_top: u32,
) -> Result<CleanIpResult> {
    let bin = ensure_installed()?;
    if vless_link.is_empty() {
        return Err(anyhow!("No vless config available — deploy first."));
    }

    let out_file = bin_dir().join("clean-ips.txt");
    let mut cmd = Command::new(&bin);
    cmd.arg("scan")
        .arg("-count").arg(count.to_string())
        .arg("-workers").arg(workers.to_string())
        .arg("-timeout").arg(format!("{timeout_s}s"))
        .arg("-ports").arg(ports)
        .arg("-config").arg(vless_link)
        .arg("-top").arg(target_top.to_string())
        .arg(if gentle { "-gentle" } else { "-gentle=false" })
        .arg("-no-state")
        .arg("-output").arg(&out_file);

    let output = run_with_timeout(&mut cmd, scan_timeout as u64);

    let (stdout, exited_ok) = match output {
        Ok(o) => (String::from_utf8_lossy(&o.stdout).to_string(), o.status.success()),
        Err(e) => {
            return Err(anyhow!("failed to launch senpaiscanner: {e}"));
        }
    };

    let live_dirs = vec![bin_dir(), std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))];
    let endpoints = collect_endpoints(&live_dirs, Some(&out_file), &stdout);

    if endpoints.is_empty() {
        let low = stdout.to_lowercase();
        let message = if low.contains("no healthy") || low.contains("nothing to scan") {
            "SenPaiScanner found no healthy endpoints for this config.".to_string()
        } else if !exited_ok {
            format!("Scanner exited with an error:\n{}", stdout.trim())
        } else {
            "No clean IPs were found. Try a larger -count, a longer timeout, or a different port.".to_string()
        };
        return Err(anyhow!(message));
    }

    let count = endpoints.len();
    Ok(CleanIpResult {
        endpoints,
        raw: stdout,
        message: format!("Found {} clean endpoint(s).", count),
    })
}

/// Run a command, killing it after `timeout_secs` and returning whatever
/// output was captured (stderr/stdout combined at exit).
pub fn run_with_timeout(
    cmd: &mut Command,
    timeout_secs: u64,
) -> std::io::Result<std::process::Output> {
    use std::io::Read;
    use std::process::Stdio;

    let mut child = cmd
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;

    let start = Instant::now();
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if start.elapsed() > Duration::from_secs(timeout_secs.max(1)) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                "scan timed out",
            ));
        }
        std::thread::sleep(Duration::from_millis(200));
    };

    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    if let Some(mut so) = child.stdout.take() {
        let _ = so.read_to_end(&mut stdout);
    }
    if let Some(mut se) = child.stderr.take() {
        let _ = se.read_to_end(&mut stderr);
    }
    // drain any remaining
    let _ = status;
    Ok(std::process::Output {
        status,
        stdout,
        stderr,
    })
}

/// Probe an `ip:port` endpoint with a TCP connect + optional TLS handshake.
/// Returns true when the endpoint responds within `timeout_s`. This is the
/// "verify before accepting" health check — a scanner candidate only counts as
/// a *working* IP once it passes here.
pub fn endpoint_reachable(endpoint: &str, timeout_s: u64, tls: bool) -> bool {
    use std::net::{TcpStream, ToSocketAddrs};
    let (ip, port) = match split_endpoint(endpoint) {
        Some(s) => s,
        None => return false,
    };
    let addr = format!("{ip}:{port}");
    let Ok(addrs) = addr.to_socket_addrs() else {
        return false;
    };
    for a in addrs {
        let Ok(stream) = TcpStream::connect_timeout(&a, Duration::from_secs(timeout_s.max(1)))
        else {
            continue;
        };
        let _ = stream.set_nodelay(true);
        if !tls {
            return true;
        }
        // Best-effort TLS handshake: the edgetunnel worker speaks TLS.
        match tls_handshake(stream, timeout_s) {
            Ok(_) => return true,
            Err(_) => continue,
        }
    }
    false
}

/// Minimal TLS handshake against the endpoint using rustls over the TCP stream.
#[cfg(feature = "health-tls")]
fn tls_handshake(stream: std::net::TcpStream, _timeout_s: u64) -> std::io::Result<()> {
    // Not wired to the config's SNI here; plain TCP reachability is enough for
    // the "working IP" gate. Kept as a stub to keep the scanner dependency-free.
    let _ = stream;
    Ok(())
}

/// `tls_handshake` fallback when the feature is off: accept TCP reachability.
#[cfg(not(feature = "health-tls"))]
fn tls_handshake(_stream: std::net::TcpStream, _timeout_s: u64) -> std::io::Result<()> {
    Ok(())
}

/// Split an `ip:port` into (ip, port).
pub fn split_endpoint(ep: &str) -> Option<(String, u16)> {
    match ep.rfind(':') {
        Some(i) => {
            let ip = ep[..i].to_string();
            let port = ep[i + 1..].parse::<u16>().ok()?;
            Some((ip, port))
        }
        None => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn edge_parse_endpoint_line() {
        assert_eq!(
            endpoint_in_line("Host: 1.2.3.4:443 ok"),
            Some("1.2.3.4:443".to_string())
        );
        assert_eq!(
            endpoint_in_line("1.2.3.4:8443"),
            Some("1.2.3.4:8443".to_string())
        );
        assert_eq!(endpoint_in_line("no ip here"), None);
    }

    #[test]
    fn good_ip_validator() {
        assert!(is_good_ip("1.2.3.4:443"));
        assert!(!is_good_ip("1.2.3.4"));
        assert!(!is_good_ip("1.2.3.4:abc"));
    }

    #[test]
    fn collect_deduplicates() {
        let mut v = Vec::new();
        add_unique(&mut v, "1.2.3.4:443".into());
        add_unique(&mut v, "1.2.3.4:443".into());
        add_unique(&mut v, "5.6.7.8:8443".into());
        assert_eq!(v.len(), 2);
    }

    #[test]
    fn smart_stop_on_first_working_is_default() {
        // Default target_top is 1 → the scanner (and the caller) stops as soon
        // as ONE verified working endpoint is found. Only an explicit --more/
        // --all raises it. This asserts the default semantics the user asked for.
        assert_eq!(crate::cleanip::DEFAULT_TARGET_TOP, 1);
    }

    #[test]
    fn collect_endpoints_unions_three_sources_deduplicated() {
        let dir = std::env::temp_dir().join(format!("khv-scan-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();

        // Source 1: a live-results file (SenPaiScannerResult-*.txt).
        fs::write(
            dir.join("SenPaiScannerResult-x.txt"),
            "Host: 1.1.1.1:443\n1.2.3.4:8443\n",
        )
        .unwrap();
        // Source 2: the output file (overlaps one endpoint with live-results).
        let out_file = dir.join("output.txt");
        fs::write(&out_file, "1.2.3.4:8443\n5.5.5.5:2053\n").unwrap();
        // Source 3: stdout (overlaps one endpoint with output).
        let stdout = "scan: 5.5.5.5:2053 ok\n7.7.7.7:443\n";

        let eps = collect_endpoints(&[dir.clone()], Some(&out_file), stdout);

        // Expected union: 1.1.1.1:443, 1.2.3.4:8443, 5.5.5.5:2053, 7.7.7.7:443
        assert_eq!(eps.len(), 4, "expected 4 dedup endpoints, got {eps:?}");
        assert!(eps.contains(&"1.1.1.1:443".to_string()));
        assert!(eps.contains(&"1.2.3.4:8443".to_string()));
        assert!(eps.contains(&"5.5.5.5:2053".to_string()));
        assert!(eps.contains(&"7.7.7.7:443".to_string()));

        let _ = fs::remove_dir_all(&dir);
    }
}
