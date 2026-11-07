# cf-console

A modern, cross-platform (Linux + Windows) terminal console that creates and
controls a **Cloudflare-Worker VLESS proxy** from zero to 100 — all in one place:

- **Interactive TUI wizard** (`textual`-based): welcome → token → account →
  worker name/UUID → deploy → get your `vless://` config → copy to clipboard
- **Headless CLI** for scripting/automation
- **Friendly error understanding**: every Cloudflare API and wrangler error is
  classified into a plain-language problem + a suggested fix
- **Clean-IP finder** (SenPaiScanner integration) for censored regions

## What it produces

A deployed worker reachable at `https://<name>.<subdomain>.workers.dev` plus a
ready-to-paste `vless://...` share link (and an xray client JSON skeleton) for
v2rayN / v2rayNG / NekoBox / sing-box, etc.

## Requirements

- Python 3.10+ (Linux or Windows)
- Node.js + `wrangler` CLI for deploying (install: `npm i -g wrangler`)
- The edgetunnel worker bundle (`_worker.js`) — auto-detected from this
  directory or `~/Projects/cf-worker-proxy/_worker.js`. Pass `--worker <path>`
  to point elsewhere.

## Run

Linux:

```bash
./cf-console.sh            # interactive TUI
./cf-console.sh cli --help # headless CLI
```

Windows:

```bat
run.bat                    @ interactive TUI
run.bat cli --help         @ headless CLI
```

First run creates `.venv` and installs dependencies automatically.

## CLI reference

```
cf-console check   [--token T] [--worker W]     # verify token + worker bundle
cf-console deploy  [--token T] [--name N] [--uuid U] [--worker W] [--account A]
cf-console config  [--token T] [--name N] [--uuid U] [--address H] [--port P]
                   [--security tls|none] [--path /]
cf-console status  [--token T] [--account A]     # list deployed workers
cf-console scan    [--token T] [--name N] [--uuid U] ...  # find clean IPs
```

The token can be passed with `--token`, or saved once to `~/.cf-console/token`.

## Local (VPN-free) testing

After deploying, test the *config* without needing the deployed host's DNS
(a workers.dev host is DNS-poisoned in some regions). Use the local harness in
`~/Projects/cf-worker-proxy/localtest/`:

```
start-local-worker.sh   # wrangler dev on LAN
start-xray.sh           # xray client against the local worker
curl --socks5-hostname 127.0.0.1:10808 https://www.google.com
```

> A passing local test proves the config/protocol is correct. It does NOT prove
> the deployed endpoint is reachable from your network — those are separate.

## Error handling

All Cloudflare HTTP errors (400/401/403/404/409/413/429/5xx and CF numeric
codes) and wrangler CLI failures are translated into human-readable
"problem + fix" guidance instead of raw stack traces.
