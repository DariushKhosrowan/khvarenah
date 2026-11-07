"""Deploy via the wrangler CLI (bundles ESM -> classic worker).

Pure-Python requests uploads only work for classic (service-worker) scripts on
the legacy /workers/scripts endpoint; modern module workers need bundling.
Wrangler (Node-based, cross-platform) is the reliable path, so we shell out to
it and interpret its output — turning every failure into a human-readable fix.

Requires `wrangler` on PATH (or set WRANGLER=...). The console guides the user
to install it if missing (npm i -g wrangler).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DeployResult:
    ok: bool
    host: str = ""
    subdomain: str = ""
    message: str = ""
    stdout: str = ""
    stderr: str = ""


class WranglerMissingError(Exception):
    pass


def wrangler_bin() -> str:
    env = os.environ.get("WRANGLER")
    if env:
        return env
    p = shutil.which("wrangler")
    if p:
        return p
    raise WranglerMissingError(
        "wrangler is not installed. Install it with:  npm i -g wrangler\n"
        "(or set WRANGLER=/path/to/wrangler)."
    )


def _parse_host(stdout: str) -> str:
    # wrangler prints "  https://<name>.<subdomain>.workers.dev"
    m = re.search(r"https://([a-z0-9-]+)\.([a-z0-9-]+)\.workers\.dev", stdout)
    if m:
        return m.group(1) + "." + m.group(2) + ".workers.dev"
    return ""


def _classify(text: str) -> str:
    """Turn a raw wrangler error into actionable guidance."""
    low = text.lower()

    if "no such file" in low or "could not find" in low:
        return "The worker bundle (worker.js/_worker.js) was not found at the configured path."
    if "syntaxerror" in low or "typeerror" in low:
        return "The worker JavaScript failed to bundle (a syntax/type error). Check your worker source."
    if "not a valid uuid" in low or "uuid" in low and "invalid" in low:
        return "The UUID you entered is malformed. Use the canonical xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx format."
    if "1101" in low:
        return ("Cloudflare error 1101: the deployed worker threw a JavaScript "
                "exception at runtime. This is NOT a token problem — the worker "
                "code itself failed (e.g. a missing env var or a bug in the "
                "bundle). Check that env.UUID is set in wrangler.toml and that "
                "the worker bundle is the correct edgetunnel file.")
    if "permission" in low or "forbidden" in low:
        return ("The API token lacks a required permission. Recreate it with "
                "Workers-Scripts:Edit + Account-Settings:Read (see the console's token guide).")
    if "authentication" in low or "unauthorized" in low or "401" in low:
        return "Authentication failed — the API token is invalid/expired. Get a fresh one."
    if "rate" in low or "429" in low:
        return "Cloudflare rate-limited you. Wait a few seconds and try again."
    if "network" in low or "timed out" in low or "econnreset" in low:
        return ("A network error occurred talking to Cloudflare. If you're in a "
                "region where api.cloudflare.com is filtered, route the console "
                "through your existing proxy or use the local test path.")
    if "no route" in low or "10404" in low:
        return "Cloudflare returned 'No route'; verify the account and worker name are correct."
    return "Check the wrangler output below; if it's a Cloudflare-side error, retry shortly."


def deploy_wrangler(token: str, account_id: str, name: str, worker_path: str,
                    uuid: str, *, timeout: int = 180) -> DeployResult:
    """Deploy `worker_path` under `name` with vars UUID=... using wrangler."""
    wbin = wrangler_bin()
    with tempfile.TemporaryDirectory(prefix="khvarenah-") as td:
        td_ = Path(td)
        # copy worker to a stable name
        src = Path(worker_path)
        dst = td_ / "worker.js"
        dst.write_bytes(src.read_bytes())
        # minimal toml
        (td_ / "wrangler.toml").write_text(
            f'name = "{name}"\n'
            'main = "worker.js"\n'
            'compatibility_date = "2024-04-01"\n'
            'compatibility_flags = ["nodejs_compat"]\n'
            f'[vars]\nUUID = "{uuid}"\n'
        )
        env = dict(os.environ)
        env["CLOUDFLARE_API_TOKEN"] = token
        env["CLOUDFLARE_ACCOUNT_ID"] = account_id
        # suppress interactive prompts
        env["CI"] = "1"
        try:
            proc = subprocess.run(
                ["node", wbin, "deploy"],
                cwd=str(td_), env=env, capture_output=True, text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return DeployResult(False, message="wrangler binary not found (tried node wrapper).")
        except subprocess.TimeoutExpired:
            return DeployResult(False, message="Deploy timed out. The worker file may be very large "
                                                "or the network is slow. Retry.")

        stdout = (proc.stdout or "") + "\n" + (proc.stderr or "")
        host = _parse_host(stdout)

        if proc.returncode == 0 and host:
            return DeployResult(True, host=host, message="Deployed OK.",
                                stdout=proc.stdout, stderr=proc.stderr)

        # error path
        friendly = _classify(stdout)
        return DeployResult(False, message=friendly, stdout=proc.stdout,
                            stderr=proc.stderr)


def create_token_instructions() -> str:
    return (
        "Token: https://dash.cloudflare.com/profile/api-tokens\n"
        "  → 'Create Token' → 'Workers Scripts' template (or custom with):\n"
        "    - Account → Workers Scripts → Edit\n"
        "    - Account → Account Settings → Read\n"
        "    - (optionally) Account → Workers KV Storage → Edit\n"
        "Copy the token that's shown once."
    )
