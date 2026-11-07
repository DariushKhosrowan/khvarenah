//! Khvarenah — Cloudflare-worker VLESS VPN console (Rust).
//!
//! A full rewrite of the Python console. Everything is **profile-scoped**:
//! tokens, accounts, generated configs, and clean IPs live per-profile, are
//! never cleared by updates, and are fully loadable.

mod cf_api;
mod cleanip;
mod stealth;
mod store;
mod updater;
mod vless;
mod worker_bundle;

use anyhow::{anyhow, Result};
use clap::{Args, Parser};
use std::path::PathBuf;

use cf_api::{Config, CfError};
use store::VlessRecord;
use vless::{rewrite_vless_with_endpoint, VlessProfile};

/// Khvarenah — Cloudflare-worker VLESS VPN console.
#[derive(Parser)]
#[command(name = "khvarenah", version = updater::VERSION, about = "Khvarenah — Cloudflare-worker VLESS VPN console (Rust)")]
struct Cli {
    /// Active profile (overrides KHVARENAH_PROFILE and the saved active profile).
    #[arg(long, global = true)]
    profile: Option<String>,

    #[command(subcommand)]
    command: Command,
}

#[derive(Parser)]
enum Command {
    /// Manage profiles
    Profile(ProfileArgs),
    /// Verify token + worker bundle
    Check(CommonArgs),
    /// Deploy worker + set UUID
    Deploy(CommonArgs),
    /// Generate vless config/link
    Config(CommonArgs),
    /// List deployed workers
    Status(CommonArgs),
    /// Find clean IPs via SenPaiScanner
    Scan(CommonArgs),
    /// Find a clean IP and emit a working vless link (stops after the first working IP by default)
    Clean(CommonArgs),
    /// Deploy then find a clean IP (full auto)
    Autopilot(CommonArgs),
    /// Show daily request usage for the active account
    Usage(CommonArgs),
    /// List saved vless configs and tokens
    History(HistoryArgs),
    /// List or switch saved Cloudflare accounts
    Accounts(AccountsArgs),
    /// Check for updates
    Upgrade,
}

#[derive(Args)]
struct ProfileArgs {
    #[command(subcommand)]
    action: ProfileAction,
}

#[derive(Parser)]
enum ProfileAction {
    /// List all profiles
    List,
    /// Create a profile (never clears existing data)
    Create { name: String },
    /// Switch the active profile
    Switch { name: String },
    /// Show current profile + data
    Show,
    /// Delete a profile (irreversible)
    Delete { name: String },
}

#[derive(clap::Args, Clone)]
struct CommonArgs {
    /// Cloudflare API token
    #[arg(long)]
    token: Option<String>,

    /// Target account ID or name
    #[arg(long)]
    account: Option<String>,

    /// Path to the worker bundle (_worker.js)
    #[arg(long)]
    worker: Option<String>,

    /// Worker name
    #[arg(long)]
    name: Option<String>,

    /// UUID for the VLESS user
    #[arg(long)]
    uuid: Option<String>,

    /// Host address (defaults to <name>.<subdomain>.workers.dev)
    #[arg(long)]
    address: Option<String>,

    /// Port (default 443)
    #[arg(long, default_value_t = 443)]
    port: u16,

    /// security: tls | none
    #[arg(long, default_value = "tls")]
    security: String,

    /// WebSocket path
    #[arg(long, default_value = "/")]
    path: String,

    /// Number of IPs to probe (clean/scan)
    #[arg(long, default_value_t = 2000)]
    count: u32,

    /// Number of scanner workers (clean/scan)
    #[arg(long, default_value_t = 25)]
    workers: u32,

    /// Per-probe timeout in seconds
    #[arg(long, default_value_t = 8)]
    timeout: u32,

    /// How many top endpoints to report (clean/scan)
    #[arg(long, default_value_t = 1)]
    top: u32,

    /// Generate configs for every clean IP found (implies a high top)
    #[arg(long)]
    all: bool,

    /// Keep scanning until this many working IPs are found
    #[arg(long)]
    more: Option<u32>,

    /// Ports to probe (e.g. "443,8443")
    #[arg(long, default_value = "443")]
    ports: String,

    /// Gentle mode (human-friendly scanning)
    #[arg(long, default_value_t = true)]
    gentle: bool,

    /// Overall scan timeout in seconds
    #[arg(long, default_value_t = 600)]
    scan_timeout: u32,

    /// Compatibility date for the deployed worker
    #[arg(long, default_value = cf_api::DEFAULT_COMPAT_DATE)]
    compat_date: String,
}

#[derive(clap::Args)]
struct HistoryArgs {
    /// Reveal stored API tokens
    #[arg(long)]
    show_tokens: bool,
}

#[derive(clap::Args)]
struct AccountsArgs {
    /// Switch the active (default) account
    #[arg(long)]
    set: Option<String>,

    /// Verify a token and add its account(s)
    #[arg(long)]
    add: Option<String>,
}

fn main() {
    let cli = Cli::parse();

    // Apply --profile by setting the env override so all store calls see it.
    if let Some(p) = &cli.profile {
        if !p.is_empty() {
            std::env::set_var("KHVARENAH_PROFILE", p);
        }
    }

    let result = match &cli.command {
        Command::Profile(a) => run_profile(a),
        Command::Check(a) => run_check(a),
        Command::Deploy(a) => run_deploy(a),
        Command::Config(a) => run_config(a),
        Command::Status(a) => run_status(a),
        Command::Scan(a) => run_scan(a, false),
        Command::Clean(a) => run_scan(a, true),
        Command::Autopilot(a) => run_autopilot(a),
        Command::Usage(a) => run_usage(a),
        Command::History(h) => run_history(h),
        Command::Accounts(a) => run_accounts(a),
        Command::Upgrade => run_upgrade(),
    };

    if let Err(e) = result {
        eprintln!("[error] {e}");
        std::process::exit(1);
    }
}

fn run_profile(a: &ProfileArgs) -> Result<()> {
    let profile = store::active_profile();
    store::ensure_profile(&profile)?;
    match &a.action {
        ProfileAction::List => {
            let list = store::list_profiles()?;
            let active = store::active_profile();
            if list.is_empty() {
                println!("No profiles yet. Create one with: khvarenah profile create <name>");
                return Ok(());
            }
            for p in &list {
                let mark = if p.name == active { "★ " } else { "  " };
                println!("{mark}{} (created {})", p.name, p.created_at);
            }
            println!("\nActive profile: {active}");
            Ok(())
        }
        ProfileAction::Create { name } => {
            store::create_profile(name)?;
            println!("✓ Profile '{name}' created. (Existing data is preserved.)");
            Ok(())
        }
        ProfileAction::Switch { name } => {
            store::set_active_profile(name)?;
            println!("✓ Active profile set to '{name}'.");
            Ok(())
        }
        ProfileAction::Show => {
            let profile = store::active_profile();
            println!("{}", store::memory_summary(&profile));
            println!("\nData directory: {}", store::profile_dir_path(&profile).display());
            Ok(())
        }
        ProfileAction::Delete { name } => {
            store::delete_profile(name)?;
            println!("✓ Profile '{name}' deleted.");
            Ok(())
        }
    }
}

// -- helpers ----------------------------------------------------------------

fn resolve_token_profile() -> String {
    store::active_profile()
}

/// Build the CF client using the right token for the target account.
fn client_for(profile: &str, args: &CommonArgs) -> Result<(Config, String, serde_json::Value), CfError> {
    let target = args.account.clone().filter(|s| !s.is_empty());
    let tok = match &target {
        Some(t) => store::get_account_token(profile, t),
        None => store::get_account_token(profile, ""),
    };
    let tok = match tok {
        Some(t) => t,
        None => match &args.token {
            Some(t) if !t.trim().is_empty() => {
                store::save_token(profile, t, "default")
                    .map_err(|e| CfError::new("Store error", e.to_string(), ""))?;
                t.trim().to_string()
            }
            _ => {
                let f = dirs_home().join(".khvarenah").join("token");
                if let Ok(s) = std::fs::read_to_string(&f) {
                    let s = s.trim().to_string();
                    if !s.is_empty() {
                        return Ok((Config::new(&s), String::new(), serde_json::json!({})));
                    }
                }
                return Err(CfError::new(
                    "No token",
                    "No token provided. Pass --token <CF_API_TOKEN>, save it to ~/.khvarenah/token, or add it via 'khvarenah accounts --add <token>'.",
                    "Create a token at https://dash.cloudflare.com/profile/api-tokens",
                ));
            }
        },
    };

    let c = Config::new(&tok);
    let (acc_id, acc_info) = resolve_account(&c, args.account.as_deref().unwrap_or(""))?;
    Ok((c, acc_id, acc_info))
}

fn dirs_home() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."))
}

fn resolve_account(c: &Config, requested: &str) -> Result<(String, serde_json::Value), CfError> {
    let accs = c.list_accounts()?;
    if accs.is_empty() {
        return Err(CfError::new(
            "No accounts",
            "This token has no Cloudflare accounts.",
            "Create an account or use a token scoped to one.",
        ));
    }
    let acc = if !requested.is_empty() {
        accs.iter().find(|a| {
            a.get("id").and_then(|i| i.as_str()) == Some(requested)
                || a.get("name").and_then(|n| n.as_str()) == Some(requested)
        })
    } else {
        let active = store::active_account_for(&store::active_profile());
        let found = accs.iter().find(|a| a.get("id").and_then(|i| i.as_str()) == Some(active.as_str()));
        found.or(accs.first())
    };
    let acc = acc.ok_or_else(|| {
        CfError::new("Account not found", format!("No account matches '{requested}'."), "List accounts with: khvarenah check")
    })?;
    let aid = acc.get("id").and_then(|i| i.as_str()).unwrap_or("").to_string();
    // remember account (subdomain discovered lazily)
    let name = acc.get("name").and_then(|n| n.as_str()).unwrap_or("");
    let _ = store::remember_account(&store::active_profile(), &aid, name, "");
    Ok((aid, acc.clone()))
}

fn default_host(profile: &str, acc_id: &str, args: &CommonArgs, c: &Config) -> String {
    if let Some(a) = &args.address {
        return a.clone();
    }
    let name = args.name.as_deref().unwrap_or("cf-worker");
    let sub = store::list_accounts(profile).get(acc_id).and_then(|a| {
        if a.subdomain.is_empty() { None } else { Some(a.subdomain.clone()) }
    });
    if let Some(sub) = sub {
        format!("{name}.{sub}.workers.dev")
    } else {
        match c.get_subdomain(acc_id) {
            Ok(s) if !s.is_empty() => {
                let _ = store::remember_account(profile, acc_id, "", &s);
                format!("{name}.{s}.workers.dev")
            }
            _ => format!("{name}.workers.dev"),
        }
    }
}

/// Build a VlessProfile from args + saved settings (profile-scoped).
fn build_profile(profile: &str, args: &CommonArgs, c: &Config, acc_id: &str) -> VlessProfile {
    let host = default_host(profile, acc_id, args, c);
    let uuid = args
        .uuid
        .clone()
        .or_else(|| store::settings(profile).uuid.clone())
        .unwrap_or_default();
    let name = args.name.clone().unwrap_or_else(|| "cf-worker".to_string());
    VlessProfile {
        uuid,
        address: host,
        port: args.port,
        security: args.security.clone(),
        path: args.path.clone(),
        sni: None,
        header_host: None,
        transport: "ws".into(),
        name,
    }
}

// -- commands ----------------------------------------------------------------

fn run_check(args: &CommonArgs) -> Result<()> {
    let profile = resolve_token_profile();
    let (c, _, _) = client_for(&profile, args).map_err(|e| anyhow!(e))?;
    let r = c.verify_token().map_err(|e| anyhow!(e))?;
    let ok = r.get("success").and_then(|s| s.as_bool()).unwrap_or(false);
    println!("{}", if ok { "Token valid." } else { "Token status: NOT valid" });

    let accs = c.list_accounts().map_err(|e| anyhow!(e))?;
    if accs.is_empty() {
        println!("No accounts found for this token.");
        return Ok(());
    }
    for acc in &accs {
        let aid = acc.get("id").and_then(|i| i.as_str()).unwrap_or("");
        let name = acc.get("name").and_then(|n| n.as_str()).unwrap_or("");
        let _ = store::remember_account(&profile, aid, name, "");
        println!("  account: {}", c.account_display(acc));
    }
    match worker_bundle::find_worker_js(args.worker.as_deref()) {
        Some(wp) => {
            let (ok2, msg) = worker_bundle::validate_worker_js(&wp);
            println!("\nWorker bundle: {}", wp.display());
            println!("  {msg}");
            if !ok2 {
                return Err(anyhow!("Worker bundle invalid: {msg}"));
            }
        }
        None => println!("\nWorker bundle: NOT FOUND (use --worker to point at _worker.js)"),
    }
    Ok(())
}

fn run_deploy(args: &CommonArgs) -> Result<()> {
    let profile = resolve_token_profile();
    store::ensure_profile(&profile)?;
    let (c, acc_id, acc_info) = client_for(&profile, args).map_err(|e| anyhow!(e))?;
    let name = worker_bundle::safe_worker_name(&args.name.clone().unwrap_or_else(|| worker_bundle::worker_name_from_account(&acc_info)));
    let worker_path = worker_bundle::find_worker_js(args.worker.as_deref())
        .ok_or_else(|| anyhow!("Could not find worker bundle. Use --worker to point at the edgetunnel _worker.js."))?;
    let (ok, msg) = worker_bundle::validate_worker_js(&worker_path);
    if !ok {
        return Err(anyhow!("Worker bundle invalid: {msg}"));
    }
    println!("Deploying '{name}' to account {} ...", store::account_label(&profile, &acc_id));
    let uuid = args.uuid.clone().unwrap_or_else(worker_bundle::generate_uuid);
    let js = std::fs::read(&worker_path)?;
    let human = stealth::humanize_worker(&js);
    let _ = c
        .deploy_script(&acc_id, &name, &human, &args.compat_date, 2)
        .map_err(|e| anyhow!(e))?;
    let host = default_host(&profile, &acc_id, args, &c);
    println!("Deploy OK.");
    println!("  UUID: {uuid}");
    println!("  worker host: {host}");

    let name_final = args.name.clone().unwrap_or_else(|| name.clone());
    let prof = VlessProfile::new(uuid, host);
    let rec = VlessRecord {
        id: uuid::Uuid::new_v4().to_string(),
        ts: store::now_iso(),
        epoch: crate::store::now_epoch(),
        uuid: prof.uuid.clone(),
        address: prof.address.clone(),
        port: prof.port,
        name: name_final,
        clean_ip: false,
        link: prof.share_link(),
        note: format!("worker={name}"),
    };
    store::remember_vless(&profile, &rec)?;
    println!("  vless link:\n    {}", prof.share_link());
    Ok(())
}

fn run_config(args: &CommonArgs) -> Result<()> {
    let profile = resolve_token_profile();
    store::ensure_profile(&profile)?;
    let (c, acc_id, _) = client_for(&profile, args).map_err(|e| anyhow!(e))?;
    let prof = build_profile(&profile, args, &c, &acc_id);
    if prof.uuid.is_empty() {
        return Err(anyhow!("--uuid required to build a config (or set a default uuid in profile settings)."));
    }
    let rec = VlessRecord {
        id: uuid::Uuid::new_v4().to_string(),
        ts: store::now_iso(),
        epoch: store::now_epoch(),
        uuid: prof.uuid.clone(),
        address: prof.address.clone(),
        port: prof.port,
        name: prof.name.clone(),
        clean_ip: false,
        link: prof.share_link(),
        note: String::new(),
    };
    store::remember_vless(&profile, &rec)?;
    println!("\n=== YOUR vless CONFIG ===");
    println!("Share link:");
    println!("  {}", prof.share_link());
    println!("\nxray client json (also saved to client-xray.json):");
    std::fs::write("client-xray.json", prof.xray_client_json())?;
    println!("  saved client-xray.json");
    println!("\nCompatibility note: for local (no-VPN) testing use --security none and point --address at your machine's LAN IP on port 8787.");
    Ok(())
}

fn run_status(args: &CommonArgs) -> Result<()> {
    let profile = resolve_token_profile();
    let (c, acc_id, _) = client_for(&profile, args).map_err(|e| anyhow!(e))?;
    let scripts = c.list_scripts(&acc_id).map_err(|e| anyhow!(e))?;
    println!("Account {} ({acc_id}) — {} worker script(s):", store::account_label(&profile, &acc_id), scripts.len());
    for s in &scripts {
        let id = s.get("id").and_then(|i| i.as_str()).unwrap_or("");
        let created = s.get("created_on").and_then(|c| c.as_str()).unwrap_or("");
        let created = created.chars().take(19).collect::<String>();
        println!("  - {id} (created {created})");
    }
    Ok(())
}

/// Run SenPaiScanner. If `clean_mode`, emit configs and obey the smart
/// stop-on-first-working / continue-on-request semantics.
fn run_scan(args: &CommonArgs, clean_mode: bool) -> Result<()> {
    let profile = resolve_token_profile();
    store::ensure_profile(&profile)?;
    let (c, acc_id, _) = client_for(&profile, args).map_err(|e| anyhow!(e))?;
    let prof = build_profile(&profile, args, &c, &acc_id);
    if prof.uuid.is_empty() {
        return Err(anyhow!("--uuid required to build the vless config for scanning."));
    }
    let link = prof.share_link();

    // Determine how many working IPs to aim for.
    let top = if args.all {
        500
    } else if let Some(more) = args.more {
        more.max(1)
    } else {
        args.top.max(1)
    };

    println!("Scanning for clean IPs against {} …", prof.address);
    println!("  (targeting {top} working endpoint(s); stops at the first one by default)");

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

    if clean_mode {
        let eps = &result.endpoints;
        if eps.is_empty() {
            return Err(anyhow!("No clean IPs found."));
        }
        let mut configs: Vec<(String, String)> = Vec::new();
        for ep in eps {
            let working_link = rewrite_vless_with_endpoint(&link, ep);
            let (ip, port) = split_endpoint(ep);
            let rec = VlessRecord {
                id: uuid::Uuid::new_v4().to_string(),
                ts: store::now_iso(),
                epoch: store::now_epoch(),
                uuid: prof.uuid.clone(),
                address: ip,
                port,
                name: format!("{} (clean IP)", prof.name),
                clean_ip: true,
                link: working_link.clone(),
                note: format!("worker={} host={}", prof.name, prof.address),
            };
            let _ = store::remember_vless(&profile, &rec);
            configs.push((ep.clone(), working_link));
        }

        // Best first
        let (best_ep, best_link) = &configs[0];
        println!("\n✓ Best clean IP: {best_ep}");
        println!("  Working vless link:\n    {best_link}");

        if configs.len() > 1 {
            println!("\nMore clean IPs ({} total):", configs.len());
            for (ep, link) in &configs[1..] {
                println!("  • {ep}\n    {link}");
            }
        }

        // Save per-profile.
        let ep_list: Vec<String> = eps.clone();
        store::save_clean_ips(&profile, &ep_list)?;
        let cfg_lines: Vec<String> = configs
            .iter()
            .map(|(ep, link)| format!("# {ep}\n{link}"))
            .collect();
        store::save_clean_configs(&profile, &cfg_lines)?;
        println!("\nSaved endpoints → {} · {} configs → {}",
            store::clean_ips_file(&profile).display(),
            configs.len(),
            store::clean_configs_file(&profile).display()
        );

        // If the user asked for more than we got, note it.
        if (top as usize) > configs.len() {
            println!("\nNote: asked for {top}, found {}. The scanner stopped when no more clean IPs were available.", configs.len());
        } else if args.more.is_none() && !args.all && configs.len() <= 1 {
            println!("\n(stopped after the first working IP — use --more N or --all to find more)");
        }
        Ok(())
    } else {
        // plain scan: list endpoints
        println!("\n=== {} ===", result.message);
        for ep in &result.endpoints {
            println!("  {ep}");
        }
        store::save_clean_ips(&profile, &result.endpoints)?;
        println!("\nAll endpoints saved to {}.", store::clean_ips_file(&profile).display());
        Ok(())
    }
}

fn split_endpoint(ep: &str) -> (String, u16) {
    match ep.rfind(':') {
        Some(i) => {
            let ip = ep[..i].to_string();
            let port = ep[i + 1..].parse::<u16>().unwrap_or(443);
            (ip, port)
        }
        None => (ep.to_string(), 443),
    }
}

fn run_autopilot(args: &CommonArgs) -> Result<()> {
    let profile = resolve_token_profile();
    let (c, acc_id, acc_info) = client_for(&profile, args).map_err(|e| anyhow!(e))?;
    let name = worker_bundle::safe_worker_name(
        args.name
            .clone()
            .unwrap_or_else(|| worker_bundle::worker_name_from_account(&acc_info))
            .as_str(),
    );
    let uuid = args.uuid.clone().unwrap_or_else(worker_bundle::generate_uuid);

    // deploy
    let mut dep = args.clone();
    dep.token = Some(c.token.clone());
    dep.account = Some(acc_id.clone());
    dep.name = Some(name.clone());
    dep.uuid = Some(uuid.clone());
    run_deploy(&dep)?;

    if stealth::enabled() {
        stealth::boundary_pause(1.0, 4.0);
    }

    // clean
    let mut cln = args.clone();
    cln.token = Some(c.token.clone());
    cln.account = Some(acc_id);
    cln.name = Some(name);
    cln.uuid = Some(uuid);
    run_scan(&cln, true)
}

fn run_usage(args: &CommonArgs) -> Result<()> {
    let profile = resolve_token_profile();
    let (c, acc_id, _) = client_for(&profile, args).map_err(|e| anyhow!(e))?;
    let scripts = c.list_scripts(&acc_id).map_err(|e| anyhow!(e))?;
    if scripts.is_empty() {
        println!("Account {} has no worker scripts yet.", store::account_label(&profile, &acc_id));
        return Ok(());
    }
    let now = chrono::Utc::now();
    let since = (now - chrono::Duration::days(1)).format("%Y-%m-%dT00:00:00Z").to_string();
    let until = now.format("%Y-%m-%dT%H:%M:%SZ").to_string();
    println!("Daily request usage — {} ({acc_id}) (since {}):", store::account_label(&profile, &acc_id), &since[..10]);
    let mut total: u64 = 0;
    for s in scripts.iter().take(20) {
        let sid = s.get("id").and_then(|i| i.as_str()).unwrap_or("");
        if sid.is_empty() {
            continue;
        }
        let data = c.script_analytics(&acc_id, sid, &since, &until).map_err(|e| anyhow!(e))?;
        let count = data.get("requestCount").and_then(|c| c.as_u64()).unwrap_or(0);
        total += count;
        println!("  • {sid:<30} {count:>12} requests");
    }
    println!("\n  TOTAL: {total} requests in the last 24h");
    Ok(())
}

fn run_history(h: &HistoryArgs) -> Result<()> {
    let profile = resolve_token_profile();
    let entries = store::list_vless(&profile, 50);
    println!("🧠 Saved vless configs (profile '{profile}'): {}", entries.len());
    for (i, r) in entries.iter().enumerate() {
        let tag = if r.clean_ip { "clean-IP" } else { "workers.dev" };
        let slot = if r.name.is_empty() { &r.address } else { &r.name };
        println!("  {}. {slot} [{tag}] — {}", i + 1, r.ts);
        println!("     {}", r.link);
    }
    let tokens = store::stored_tokens(&profile);
    if !tokens.is_empty() {
        println!("\n🔑 Saved tokens: {}", tokens.len());
        for (label, e) in &tokens {
            if h.show_tokens {
                println!("  • {label}: {}", e.token);
            } else {
                println!("  • {label}: •••• (use --show-tokens to reveal)");
            }
        }
    }
    let accs = store::list_accounts(&profile);
    if !accs.is_empty() {
        println!("\n☁️ Saved accounts: {}", accs.len());
        for (aid, info) in &accs {
            let name = if info.name.is_empty() { aid.clone() } else { info.name.clone() };
            let sub = if info.subdomain.is_empty() { String::new() } else { format!(" · {}.workers.dev", info.subdomain) };
            println!("  • {name} ({aid}){sub}");
        }
    }
    Ok(())
}

fn run_accounts(a: &AccountsArgs) -> Result<()> {
    let profile = resolve_token_profile();
    store::ensure_profile(&profile)?;
    if let Some(tok) = &a.add {
        let c = Config::new(tok);
        let r = c.verify_token().map_err(|e| anyhow!(e))?;
        if !r.get("success").and_then(|s| s.as_bool()).unwrap_or(false) {
            return Err(anyhow!("Token could not be verified."));
        }
        let accs = c.list_accounts().map_err(|e| anyhow!(e))?;
        if accs.is_empty() {
            return Err(anyhow!("This token has no Cloudflare accounts."));
        }
        let had_tokens = !store::stored_tokens(&profile).is_empty();
        let mut first = String::new();
        for acc in &accs {
            let aid = acc.get("id").and_then(|i| i.as_str()).unwrap_or("").to_string();
            let name = acc.get("name").and_then(|n| n.as_str()).unwrap_or("");
            let _ = store::remember_account(&profile, &aid, name, "");
            let _ = store::save_token(&profile, tok, &aid);
            if first.is_empty() {
                first = aid;
            }
        }
        if !had_tokens {
            let _ = store::save_token(&profile, tok, "default");
        }
        if !first.is_empty() {
            let _ = store::set_active_profile(&profile);
        }
        println!("✓ Added {} account(s) from this token:", accs.len());
        for acc in &accs {
            let aid = acc.get("id").and_then(|i| i.as_str()).unwrap_or("");
            let name = acc.get("name").and_then(|n| n.as_str()).unwrap_or("");
            println!("  • {name} ({aid})");
        }
        return Ok(());
    }

    let accs = store::list_accounts(&profile);
    if accs.is_empty() {
        println!("No saved accounts in profile '{profile}' yet. Add one:");
        println!("  khvarenah accounts --add <CF_API_TOKEN>");
        return Ok(());
    }

    if let Some(switch) = &a.set {
        if !accs.contains_key(switch) {
            return Err(anyhow!("No saved account '{switch}'. Use its account ID or name from the list below."));
        }
        if store::set_active_account(&profile, switch) {
            println!("✓ Active account set to: {} ({switch})", store::account_label(&profile, switch));
        }
        return Ok(());
    }

    println!("☁️ Saved accounts (profile '{profile}'): {}", accs.len());
    for (aid, info) in &accs {
        let name = if info.name.is_empty() { aid.clone() } else { info.name.clone() };
        let sub = if info.subdomain.is_empty() { String::new() } else { format!(" · {}.workers.dev", info.subdomain) };
        let tok_mark = if store::get_account_token(&profile, aid).is_some() { " 🔑" } else { "" };
        println!("    {name} ({aid}){sub}{tok_mark}");
    }
    println!("\nSwitch accounts:  khvarenah accounts --set <account-id>");
    println!("Add an account:  khvarenah accounts --add <CF_API_TOKEN>");
    Ok(())
}

fn run_upgrade() -> Result<()> {
    println!("Current version: {}", updater::VERSION);
    let (available, msg) = updater::check_for_update()?;
    println!("{msg}");
    if available {
        println!("Run from source, or fetch the new release binary from GitHub: https://github.com/{}/releases", updater::REPO);
    }
    Ok(())
}
