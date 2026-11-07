<div align="center">

# ✦ Khvarenah (خوَرنه) · **Khosrowan**

**The ancient Persian royal glory — a Cloudflare-Worker VLESS VPN console in your terminal.**

Create and control a Cloudflare-Worker VLESS VPN — from zero to 100, entirely from your terminal. Cross-platform (Linux · Windows) · Interactive TUI wizard + headless CLI · Friendly error explanations.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-2ea44f)](https://github.com/DariushKhosrowan/cf-console)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![GitHub Pages](https://img.shields.io/badge/Docs-Site-2ea44f)](https://dariushkhosrowan.github.io/cf-console/)
[![Khosrowan](https://img.shields.io/badge/Khosrowan-khosrowan.ir-2ea44f)](https://khosrowan.ir)
[![Telegram](https://img.shields.io/badge/Telegram-%40Khosrowan_ir-26A5E4?logo=telegram&logoColor=white)](https://t.me/Khosrowan_ir)

**A modern terminal console that walks you through deploying a Cloudflare Workers proxy (VLESS over WebSocket) — verify your token, pick an account, deploy the worker, and get a ready-to-copy `vless://` config. If anything goes wrong, it tells you *what* the problem is and *how to fix it* — not a raw stack trace.**

**A [Khosrowan](https://khosrowan.ir) tool · [@Khosrowan_ir](https://t.me/Khosrowan_ir) on Telegram**

</div>

---

## 🎬 The console in action

The interactive wizard guides you **0 → 100** — welcome, token, account, worker, deploy, config, done:

![Welcome](docs/img/welcome.png)

| Token | Account | Worker |
|---|---|---|
| ![Token](docs/img/token.png) | ![Account](docs/img/account.png) | ![Worker](docs/img/worker.png) |

| Deploy | Config | Done |
|---|---|---|
| ![Deploy](docs/img/deploy.png) | ![Config](docs/img/config.png) | ![Done](docs/img/done.png) |

---

## ✦ What is Khvarenah?

**خوَرنه (Khvarenah)** is the Avestan term for *divine royal glory / radiance* — a sacred inner fire that lets one rise above every barrier. That is exactly what this tool does: it gives you the glory to reach over censorship walls. The app greets you with the golden Khosrowan emblem, rendered as true-color terminal art.

## ✨ Why Khvarenah?

| Pain point | What Khvarenah does |
|---|---|
| Setup is a maze of dashboards & APIs | A **0 → 100 wizard**: token → account → deploy → config, all in one place |
| Raw JSON/stack-trace errors | **Friendly error understanding**: every Cloudflare API & wrangler error → *problem + fix* |
| No CLI on Linux *and* Windows | Works identically on both, with native launchers |
| Need to paste a config into a client | Generates the `vless://` share link + xray client JSON, copies to clipboard |
| Workers.dev DNS-blocked in censored regions | Built-in **clean-IP finder** (SenPaiScanner) + **VPN-free local test** harness |

---

## 🚀 Quick install

### For non-programmers (recommended)

Install the **.deb** (Linux) or **.exe** (Windows) from
[GitHub Releases](https://github.com/DariushKhosrowan/cf-console/releases) —
both bundle Python, so nothing else is needed.

**Linux** — one command (no git, no pip, no coding):

```bash
curl -fsSL https://raw.githubusercontent.com/DariushKhosrowan/cf-console/main/install.sh | bash
```

…or grab the `.deb` directly (note: the `./khvarenah_*.deb` glob only works if a matching file is in the current folder, so download it first):

```bash
curl -fsSL -o /tmp/khvarenah.deb \
  https://github.com/DariushKhosrowan/cf-console/releases/latest/download/khvarenah_0.1.0_amd64.deb
sudo apt install /tmp/khvarenah.deb
```

Then just run `khvarenah` from any terminal.

**Windows** — download `khvarenah.exe` and double-click it.

### For developers

> Requires **Python 3.10+**. The `install.sh` script creates a venv for you
> (this avoids the PEP 668 "externally-managed environment" error on modern
> Ubuntu/Debian). Installing adds the `khvarenah` command to your PATH.

```bash
git clone https://github.com/DariushKhosrowan/cf-console.git
cd cf-console
./install.sh                # creates .venv, installs, and launches the TUI
# or, if you know what you're doing:
python3 -m venv .venv
.venv/bin/pip install -e .
```

Then run it from anywhere:

```bash
khvarenah                  # launch the interactive TUI wizard (golden emblem welcome)
khvarenah cli --help       # headless CLI
```

### Windows (developer)

```bat
git clone https://github.com/DariushKhosrowan/cf-console.git
cd cf-console
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\khvarenah
.venv\Scripts\khvarenah cli --help
```

### Prerequisites for deploying

- **Python 3.10+** — for the console itself.
- **Node.js + [wrangler](https://developers.cloudflare.com/workers/wrangler/)** — the console shells out to wrangler to deploy (it bundles the worker for you). Install once with:
  ```bash
  npm install -g wrangler
  ```
- **A Cloudflare API token** with `Workers Scripts: Edit` and `Account Settings: Read` permissions ([create one here](https://dash.cloudflare.com/profile/api-tokens)). Save it once to `~/.cf-console/token` — or pass `--token` each run.

> 💡 The console auto-detects the [edgetunnel](https://github.com/cmliu/edgetunnel) worker bundle from this repo or `~/Projects/cf-worker-proxy/_worker.js`. Point elsewhere with `--worker <path>`.

---

## 🖥️ The interactive wizard (TUI)

```
Welcome → Token → Account → Worker name/UUID → Deploy → Your vless config → Done
```

1. **Welcome** — the golden Khosrowan emblem + overview of the steps.
2. **Token** — paste your Cloudflare API token; it's verified live, with a permission guide if anything's off.
3. **Account** — pick the account the worker should live on.
4. **Worker** — name your worker + generate (or paste) a UUID.
5. **Deploy** — wrangler uploads the worker and sets `UUID`. Failures are explained with a fix.
6. **Config** — your `vless://` share link appears; press `c` to copy it to your clipboard.
7. **Done** — deployment details + local-test guidance.

---

## 💻 Headless CLI

```
khvarenah cli check   [--token T] [--worker W]                 # verify token + worker bundle
khvarenah cli deploy  [--token T] [--name N] [--uuid U] [--worker W] [--account A]
khvarenah cli config  [--token T] [--name N] [--uuid U] [--address H] [--port P]
                      [--security tls|none] [--path /]
khvarenah cli status  [--token T] [--account A]                 # list deployed workers
khvarenah cli scan    [--token T] [--name N] [--uuid U] ...      # find clean IPs
khvarenah cli --version
```

**Examples**

```bash
# Verify your token and the local worker bundle
khvarenah cli check --token $CF_TOKEN

# Deploy and get a vless link
khvarenah cli deploy --token $CF_TOKEN --name my-vpn --uuid <your-uuid>

# Generate a config (e.g. for a local, no-TLS test) and save client-xray.json
khvarenah cli config --token $CF_TOKEN --name my-vpn --uuid <uuid> \
    --address 192.168.1.50 --port 8787 --security none

# Find clean Cloudflare IPs for your deployed worker
khvarenah cli scan --token $CF_TOKEN --name my-vpn --uuid <uuid>
```

Exit codes: `0` OK · `1` user/validation error · `2` Cloudflare error (message + fix printed).

---

## 🧠 Error understanding

Every Cloudflare API HTTP error (400/401/403/404/409/413/429/5xx) and CF numeric code, plus wrangler CLI failures, is translated into **plain-language "problem + fix" guidance** instead of a raw traceback — e.g. a `1101` runtime exception is correctly explained as a worker-code issue, *not* a flawed problem.

---

## 🧪 Testing without a VPN (censored regions)

A `workers.dev` host is often DNS-blocked locally. Khvarenah supports a **VPN-free local harness** (see `~/Projects/cf-worker-proxy/localtest/`):

```bash
start-local-worker.sh   # wrangler dev on your LAN
start-xray.sh           # xray client pointing at the local worker
curl --socks5-hostname 127.0.0.1:10808 https://www.google.com   # → 200
```

> A passing *local* test proves the protocol/config is correct — it does **not** prove the deployed endpoint is reachable from your network. Those are separate checks.

---

## 🗂️ Project structure

```
cf-console/
├── pyproject.toml         # packaging + console_scripts (khvarenah)
├── cf-console.sh          # legacy Linux/macOS launcher
├── run.bat                # legacy Windows launcher
├── run.py                 # legacy entry point (TUI default, `cli` subcommand)
├── test_classifier.py     # unit tests (error classifier, config gen)
└── khvarenah/
    ├── assets/golden.png  # golden logo (terminal banner source)
    ├── banner.py          # renders the golden emblem as ANSI terminal art
    ├── cli.py             # headless CLI
    ├── tui.py             # Textual TUI wizard (welcome shows the emblem)
    ├── cf_api.py          # Cloudflare Workers API client + error classification
    ├── deploy_wrangler.py # wrangler deploy + error classification
    ├── vless.py           # vless share-link / client config generation
    ├── cleanip.py         # SenPaiScanner clean-IP finding
    └── worker_bundle.py   # worker discovery + validation
```

---

## 🧪 Development

```bash
.venv/bin/python -m pytest -v   # run the test suite
```

---

## 🖊️ License

MIT — free to use, modify, and share. See [LICENSE](LICENSE).

---

**A [Khosrowan](https://khosrowan.ir) tool.** Join us on Telegram: [@Khosrowan_ir](https://t.me/Khosrowan_ir).

**Questions?** Open an [issue](https://github.com/DariushKhosrowan/cf-console/issues) — and if the error you hit isn't explained well, tell us; we want Khvarenah to understand it.
