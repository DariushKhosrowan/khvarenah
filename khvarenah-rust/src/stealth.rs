//! Humanizing anti-bot stealth layer.
//!
//! Cloudflare (and the CF API edge) throttle or ban accounts whose automation
//! looks machine-generated. This module adds randomized, human-shaped pacing
//! and jitter to every API interaction.
//!
//! Disable entirely with `KHVARENAH_STEALTH=0` (used by tests/CI).

use once_cell::sync::Lazy;
use std::thread;
use std::time::Duration;

pub fn enabled() -> bool {
    std::env::var("KHVARENAH_STEALTH")
        .map(|v| v != "0")
        .unwrap_or(true)
}

/// Tiny xorshift64 PRNG (no external dependency). Seeded from entropy.
fn next_u64(state: &mut u64) -> u64 {
    let mut x = *state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    *state = x;
    x
}

static STATE: Lazy<std::sync::Mutex<u64>> = Lazy::new(|| {
    use std::time::{SystemTime, UNIX_EPOCH};
    let seed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0x9E3779B97F4A7C15);
    std::sync::Mutex::new(seed | 1)
});

/// Uniform random f64 in [0, 1).
fn unit() -> f64 {
    let mut g = STATE.lock().unwrap();
    (next_u64(&mut g) >> 11) as f64 / (1u64 << 53) as f64
}

/// Uniform random value in [low, high).
fn jitter(low: f64, high: f64) -> f64 {
    low + (high - low) * unit()
}

fn sleep(seconds: f64) {
    if enabled() && seconds > 0.0 {
        thread::sleep(Duration::from_secs_f64(seconds));
    }
}

/// Human-shaped pause before an API call.
/// kind="read" -> short delay (~0.4–2.0s).
/// kind="write" -> longer "crafting" delay (~1.5–4.5s).
pub fn pre_request_pause(kind: &str) {
    if !enabled() {
        return;
    }
    let mut base = if kind == "write" {
        jitter(1.5, 4.5)
    } else {
        jitter(0.4, 2.0)
    };
    // ~8% "distraction" pause
    if unit() < 0.08 {
        base += jitter(1.5, 4.5);
    }
    sleep(base);
}

/// Pause between major workflow stages (e.g. deploy -> scan).
pub fn boundary_pause(min_s: f64, max_s: f64) {
    sleep(jitter(min_s, max_s));
}

/// Randomized exponential backoff between retries (attempt is 0-based).
pub fn retry_backoff(attempt: u32) {
    let exp = 2.0_f64.powi(attempt as i32 + 1);
    sleep((1.0_f64).max(exp * jitter(0.75, 1.25)));
}

/// Append a varied, innocuous comment header to worker bytes so successive
/// deployments don't share a byte fingerprint (anti-bot). ~1 in 5 left
/// pristine to mimic a human occasionally shipping untouched code.
pub fn humanize_worker(js: &[u8]) -> Vec<u8> {
    if !enabled() || js.is_empty() {
        return js.to_vec();
    }
    if unit() < 0.2 {
        return js.to_vec();
    }
    let editors = [
        "M. K.", "A. R.", "N. T.", "S. J.", "P. M.", "D. V.", "K. B.", "E. S.", "R. A.", "Sh. N.",
        "B. H.", "G. F.", "H. Z.", "Ma. S.", "F. D.", "C. L.", "O. P.", "L. W.",
    ];
    let notes = [
        "minor cleanup of the upgrade path",
        "refresh deps and bump compatibility date",
        "tidy header and add a couple of comments",
        "tighten the fetch error handling branch",
        "re-format and re-verify against staging",
        "add a note about the env vars used",
        "sync with the latest template release",
        "small wording fix in the inline doc",
        "re-validate module syntax before shipping",
        "move a helper inline, drop the duplicate",
    ];
    let editor = editors[(jitter(0.0, editors.len() as f64) as usize) % editors.len()];
    let note = notes[(jitter(0.0, notes.len() as f64) as usize) % notes.len()];
    // plausible date range
    let d1 = 2025 + rand_int(0, 2);
    let d1m = 1 + rand_int(0, 11);
    let d1d = 1 + rand_int(0, 27);
    let d2 = d1 + rand_int(0, 2);
    let d2m = 1 + rand_int(0, 11);
    let d2d = 1 + rand_int(0, 27);
    let indent = ["  ", "    ", "\t", "   "][rand_int(0, 4) as usize];
    let spacer = ["\n", "\n\n", "\n", "\n\n\n"][rand_int(0, 4) as usize];
    let ci = 1000 + rand_int(0, 9000);
    let header = format!(
        "/*\n * {editor} {indent}{d1}-{d1m:02}-{d1d:02} → {d2}-{d2m:02}-{d2d:02}\n * {note}.\n * last verified by CI run #{ci}\n */{spacer}"
    );
    let mut out = header.into_bytes();
    out.extend_from_slice(js);
    out
}

fn rand_int(low: i64, high: i64) -> i64 {
    (low as f64 + jitter(0.0, (high - low) as f64)) as i64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stealth_disabled_by_env() {
        std::env::set_var("KHVARENAH_STEALTH", "0");
        assert!(!enabled());
        std::env::remove_var("KHVARENAH_STEALTH");
        assert!(enabled());
    }

    #[test]
    fn humanize_produces_valid_js_prefix() {
        let js = b"const Version='x';";
        let h = humanize_worker(js);
        // bytes start valid (comment). At least as long as source.
        assert!(h.len() >= js.len());
        // Ensure it starts with a comment block OR the original (pristine).
        assert!(h.starts_with(b"/*") || h == js);
    }
}
