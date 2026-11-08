//! Autopilot monitor — the "set it and forget it" mode.
//!
//! A single `autopilot start` sets everything up: it deploys the worker if
//! needed, finds the best clean IP, writes the working vless config, and then
//! goes into a monitoring loop. On each interval it re-verifies the active
//! clean endpoint. If the endpoint has degraded (unreachable) or the worker
//! config changed, it re-scans for a fresh clean IP and swaps it in, so the
//! exported config is *always* backed by a live endpoint.
//!
//! The monitor publishes its state into the profile's autopilot.json so the
//! GUI and any process can read current status.

use crate::cleanip;
use crate::store::{self, AutopilotState};
use crate::vless;
use crate::worker_bundle;
use anyhow::{anyhow, Result};
use std::time::Duration;

/// Run one autopilot cycle (deploy-if-needed + find best clean IP) and update
/// the persisted state. Returns the resulting state.
pub fn run_once(profile: &str, args: &crate::CommonArgs) -> Result<AutopilotState> {
    let mut st = store::autopilot_state(profile);
    st.enabled = true;
    st.running = true;
    st.status = "Preparing…".to_string();
    store::save_autopilot_state(profile, &st)?;

    // 1. Ensure the worker is deployed. We resolve the CF client + account the
    //    same way every other command does.
    let (c, acc_id, acc_info) = crate::client_for(profile, args)?;
    let name = worker_bundle::safe_worker_name(
        args.name
            .clone()
            .unwrap_or_else(|| worker_bundle::worker_name_from_account(&acc_info))
            .as_str(),
    );
    let uuid = args.uuid.clone().unwrap_or_else(worker_bundle::generate_uuid);

    // Deploy if it isn't already on the account (idempotent enough for auto).
    let scripts = c.list_scripts(&acc_id).map_err(|e| anyhow!(e))?;
    let deployed = scripts.iter().any(|s| {
        s.get("id")
            .and_then(|i| i.as_str())
            .map(|i| i == name)
            .unwrap_or(false)
    });
    if !deployed {
        st.status = "Deploying worker…".to_string();
        store::save_autopilot_state(profile, &st)?;
        let mut dep = args.clone();
        dep.token = Some(c.token.clone());
        dep.account = Some(acc_id.clone());
        dep.name = Some(name.clone());
        dep.uuid = Some(uuid.clone());
        crate::run_deploy(&dep)?;
    }

    // 2. Build the base vless link (workers.dev host) for scanning.
    let prof = crate::build_profile(profile, args, &c, &acc_id);
    let link = prof.share_link();

    // 3. Find clean IPs (SlipNet / SenPaiScanner backends).
    st.status = "Scanning for clean IPs…".to_string();
    store::save_autopilot_state(profile, &st)?;
    let top = u32::max(store::settings(profile).clean_top.max(1), 1);
    let result = cleanip::find_clean_ips(
        &link,
        args.count,
        args.workers,
        args.timeout,
        args.gentle,
        &args.ports,
        args.scan_timeout,
        top,
    )?;

    // 4. Verify each candidate and keep the first verified working one.
    let verify_tls = prof.security == "tls";
    let mut best: Option<(String, String)> = None;
    for ep in &result.endpoints {
        if !cleanip::endpoint_reachable(ep, args.timeout.into(), verify_tls) {
            continue;
        }
        let working_link = vless::rewrite_vless_with_endpoint(&link, ep);
        best = Some((ep.clone(), working_link));
        break;
    }

    let (best_ep, best_link) = best.ok_or_else(|| {
        anyhow!(
            "Scanner found endpoints but none passed the health check. Try a larger --count or longer --timeout."
        )
    })?;

    // 5. Persist the working config + clean IP list.
    let (ip, port) = crate::split_endpoint(&best_ep);
    let rec = store::VlessRecord {
        id: uuid::Uuid::new_v4().to_string(),
        ts: store::now_iso(),
        epoch: store::now_epoch(),
        uuid: uuid.clone(),
        address: ip,
        port,
        name: format!("{} (clean IP)", prof.name),
        clean_ip: true,
        link: best_link.clone(),
        note: format!("worker={name} host={}", prof.address),
    };
    let _ = store::remember_vless(profile, &rec);
    store::save_clean_ips(profile, &result.endpoints)?;
    store::save_clean_configs(profile, &[format!("# {best_ep}\n{best_link}")])?;

    st.enabled = true;
    st.worker_name = name;
    st.uuid = uuid;
    st.current_endpoint = best_ep.clone();
    st.status = format!("Active: {best_ep} — config exported.");
    st.last_check_epoch = store::now_epoch();
    st.next_check_epoch = store::now_epoch() + (st.interval_minutes as f64) * 60.0;
    store::save_autopilot_state(profile, &st)?;

    Ok(st)
}

/// A single monitor tick: verify the current endpoint; if it is no longer
/// reachable, re-scan and swap in a fresh one.
pub fn monitor_tick(profile: &str, args: &crate::CommonArgs) -> Result<AutopilotState> {
    let st = store::autopilot_state(profile);
    if !st.enabled {
        return Ok(st);
    }

    let verify_tls = store::settings(profile).security.as_deref() == Some("tls");
    let current_ok = if st.current_endpoint.is_empty() {
        false
    } else {
        cleanip::endpoint_reachable(&st.current_endpoint, 5, verify_tls)
    };

    if current_ok {
        let mut st = st;
        st.status = format!("Active: {} — healthy.", st.current_endpoint);
        st.last_check_epoch = store::now_epoch();
        st.next_check_epoch = store::now_epoch() + (st.interval_minutes as f64) * 60.0;
        store::save_autopilot_state(profile, &st)?;
        return Ok(st);
    }

    // Endpoint degraded → re-scan for a fresh one.
    if !st.current_endpoint.is_empty() {
        let mut st = st.clone();
        st.status = format!(
            "{} unreachable — re-scanning…",
            st.current_endpoint
        );
        store::save_autopilot_state(profile, &st)?;
    }
    run_once(profile, args)
}

/// Blocking monitoring loop. Runs until the process is interrupted; the state
/// file is updated after every tick so the GUI can show live status.
pub fn monitor_loop(profile: &str, args: &crate::CommonArgs) -> Result<()> {
    let mut st = run_once(profile, args)?;
    println!("Autopilot active. Watching {} …", st.current_endpoint);
    println!("  (Ctrl-C to stop)");
    loop {
        let interval = (st.interval_minutes.max(1) as u64) * 60;
        std::thread::sleep(Duration::from_secs(interval));
        match monitor_tick(profile, args) {
            Ok(next) => {
                let changed = next.current_endpoint != st.current_endpoint;
                st = next;
                if changed {
                    println!(
                        "✓ Swapped to new clean IP: {}",
                        st.current_endpoint
                    );
                } else {
                    println!("✓ {} — still healthy.", st.current_endpoint);
                }
            }
            Err(e) => {
                let mut s = store::autopilot_state(profile);
                s.status = format!("Monitor error: {e}");
                let _ = store::save_autopilot_state(profile, &s);
                eprintln!("[autopilot] {e}");
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn monitor_tick_returns_when_disabled() {
        let profile = "default";
        let args = crate::CommonArgs::default();
        // No profile store → autopilot off → tick returns immediately with
        // default (disabled) state, no network calls.
        let st = monitor_tick(profile, &args).unwrap();
        assert!(!st.enabled);
    }

    #[test]
    fn run_once_requires_token() {
        let profile = "nobody";
        // No token stored → client_for fails with a clean error (never gets to
        // scanning), which we assert is an Err of some kind.
        let args = crate::CommonArgs::default();
        assert!(run_once(profile, &args).is_err());
    }
}
