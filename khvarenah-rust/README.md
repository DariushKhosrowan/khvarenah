# Khvarenah (Rust)

Cloudflare-worker VLESS VPN console — a complete Rust rewrite of the Python
`khvarenah` console. Everything is **profile-scoped**: tokens, accounts,
generated vless configs, and clean IPs live per-profile, are fully loadable,
and are **never cleared** by an update or redeploy (state is merge-only).

## Build

```bash
cargo build --release
# binary: target/release/khvarenah
```

Requires a Rust toolchain; all dependencies are vendored/offline-friendly.

## Commands

```
khvarenah profile list|create <name>|switch <name>|show|delete <name>
khvarenah check      [--token T] [--worker path]
khvarenah deploy     [--token T] [--account A] [--name N] [--uuid U] [--worker path]
khvarenah config     [--token T] [--account A] [--uuid U] [--address H] [--port N]
                    [--security tls|none] [--path P]
khvarenah status     [--token T] [--account A]
khvarenah scan|clean [--token T] [--account A] [--uuid U] [--count N] [--workers N]
                    [--timeout S] [--top N] [--all] [--more N] [--ports P]
                    [--gentle] [--scan-timeout S]
khvarenah autopilot [--token T] [--account A] [--name N]
khvarenah usage      [--token T] [--account A]
khvarenah history    [--show-tokens]
khvarenah accounts   [--add <CF_API_TOKEN>] [--set <account-id>]
khvarenah upgrade
```

### Active profile

Selected by `KHVARENAH_PROFILE` env var, `--profile <name>` (global flag), or
the saved active profile. Defaults to `default`.

## Smart clean-IP

`clean` targets **one** working IP by default and stops there. To gather more,
pass `--more N` (ask for N working IPs) or `--all` (collect everything the
scanner finds). Clean IPs and generated configs are saved per-profile.

## Stealth / anti-bot

Human-shaped pacing, jitter, and worker byte-fingerprint humanization are
on by default. Disable with `KHVARENAH_STEALTH=0`.

## Storage layout

```
~/.khvarenah/
  config.json                 # global: active_profile, version
  profiles/<name>/
    meta.json                 # name, created_at, updated_at
    tokens.json               # account -> token
    accounts.json             # account_id -> {name, subdomain}
    history.json              # generated vless configs
    clean-ips.txt             # endpoints found by the clean-IP scanner
    clean-configs.txt         # generated working vless links
    settings.json             # per-profile parameters
```
