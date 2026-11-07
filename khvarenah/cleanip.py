"""Clean-IP finding via SenPaiScanner (https://github.com/MatinSenPai/SenPaiScanner).

SenPaiScanner probes Cloudflare IPs, validates the best ones through a real
vless config (it bundles an Xray core), and exports clean endpoints.  We shell
out to its standalone CLI in plain-text mode, collect its live-results file,
and return the healthy endpoints.

Binary is auto-installed to ~/.khvarenah/bin/senpaiscanner.
"""

from __future__ import annotations

import glob
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

BIN_DIR = Path.home() / ".khvarenah" / "bin"
BIN = BIN_DIR / ("senpaiscanner.exe" if os.name == "nt" else "senpaiscanner")
RELEASE = "v1.1.1"
GOOD_IP = re.compile(r"^\d{1,3}(\.\d{1,3}){3}:\d+$")
ENDPOINT_IN_LINE = re.compile(r"(?<!\d)(\d{1,3}(\.\d{1,3}){3}):(\d+)")


@dataclass
class CleanIPResult:
    ok: bool
    endpoints: List[str] = field(default_factory=list)   # "ip:port"
    raw: str = ""
    message: str = ""


def platform_asset() -> str:
    if os.name == "nt":
        if platform.machine().lower() in ("amd64", "x86_64"):
            return "SenPaiScanner-1.1.1-cli-windows-amd64.exe"
        return "SenPaiScanner-1.1.1-cli-windows-arm64.exe"
    if sys.platform == "darwin":
        if platform.machine().lower() in ("arm64", "aarch64"):
            return "SenPaiScanner-1.1.1-cli-macos-apple-silicon"
        return "SenPaiScanner-1.1.1-cli-macos-intel"
    arch = platform.machine().lower()
    if arch in ("arm64", "aarch64"):
        return "SenPaiScanner-1.1.1-cli-linux-arm64"
    if "arm" in arch:
        return "SenPaiScanner-1.1.1-cli-linux-armv7"
    return "SenPaiScanner-1.1.1-cli-linux-amd64"


def install() -> tuple[bool, str]:
    """Download the SenPaiScanner CLI for this platform."""
    import urllib.request
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    asset = platform_asset()
    url = (f"https://github.com/MatinSenPai/SenPaiScanner/releases/download/"
           f"{RELEASE}/{asset}")
    tmp = BIN_DIR / (asset + ".part")
    try:
        urllib.request.urlretrieve(url, tmp)
    except Exception as e:  # noqa: BLE001
        return False, f"Download failed: {e}"
    tmp.rename(BIN)
    BIN.chmod(0o755)
    return True, f"Installed SenPaiScanner → {BIN}"


def ensure_installed() -> tuple[bool, str]:
    if BIN.exists():
        return True, str(BIN)
    return install()


def _collect_endpoints(live_pattern: Optional[str], out_file: Optional[Path],
                       stdout: str) -> List[str]:
    """Gather endpoints from live-results file, -output file, and stdout."""
    seen: List[str] = []

    def add(e: str):
        e = e.strip().lower()
        if GOOD_IP.match(e) and e not in seen:
            seen.append(e)

    # live results file — the scanner writes these to the CWD, so glob BOTH
    # the explicitly-passed pattern (BIN_DIR) and the current directory.
    patterns = []
    if live_pattern:
        patterns.append(live_pattern)
    patterns.append(str(Path.cwd() / "SenPaiScannerResult-*.txt"))
    for pat in patterns:
        for f in sorted(glob.glob(pat), reverse=True):
            try:
                for line in Path(f).read_text().splitlines():
                    m = ENDPOINT_IN_LINE.search(line)
                    if m:
                        add(f"{m.group(1)}:{m.group(3)}")
            except OSError:
                pass
    # explicit output file
    if out_file and out_file.exists():
        for line in out_file.read_text().splitlines():
            add(line)
    # stdout fallback
    for m in ENDPOINT_IN_LINE.finditer(stdout):
        add(f"{m.group(1)}:{m.group(3)}")
    return seen


def find_clean_ips(vless_link: str, *, count: int = 2000, workers: int = 50,
                   timeout_s: int = 8, gentle: bool = True, ports: str = "443",
                   scan_timeout: int = 600, on_progress=None) -> CleanIPResult:
    """Run SenPaiScanner against the vless link, return clean endpoints."""
    ok, msg = ensure_installed()
    if not ok:
        return CleanIPResult(False, message=msg)
    if not vless_link:
        return CleanIPResult(False, message="No vless config available — deploy first.")

    out_file = BIN_DIR / "clean-ips.txt"
    live_glob = str(BIN_DIR / "SenPaiScannerResult-*.txt")

    cmd = [str(BIN), "scan",
           "-count", str(count),
           "-workers", str(workers),
           "-timeout", f"{timeout_s}s",
           "-ports", ports,
           "-config", vless_link,
           "-top", "25",
           "-gentle"] if gentle else [str(BIN), "scan",
           "-count", str(count),
           "-workers", str(workers),
           "-timeout", f"{timeout_s}s",
           "-ports", ports,
           "-config", vless_link,
           "-top", "25",
           "-gentle=false"]
    cmd += ["-no-state", "-output", str(out_file)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=scan_timeout)
    except FileNotFoundError:
        return CleanIPResult(False, message="senpaiscanner binary not found.")
    except subprocess.TimeoutExpired:
        proc = None
        # try to salvage whatever the live file already captured
        endpoints = _collect_endpoints(live_glob, out_file, "")
        if endpoints:
            return CleanIPResult(True, endpoints=endpoints,
                                 message=f"Scan still running when the window closed, "
                                         f"but {len(endpoints)} clean endpoint(s) are already known.")
        return CleanIPResult(False, message="Scan timed out (reduce count or workers).")

    stdout = proc.stdout or ""
    endpoints = _collect_endpoints(live_glob, out_file, stdout)

    if not endpoints:
        msg2 = "No clean IPs were found. Try a larger -count, a longer timeout, or a different port."
        if "no healthy" in stdout.lower() or "nothing to scan" in stdout.lower():
            msg2 = "SenPaiScanner found no healthy endpoints for this config."
        return CleanIPResult(False, endpoints=[], raw=stdout, message=msg2)

    return CleanIPResult(True, endpoints=endpoints, raw=stdout,
                         message=f"Found {len(endpoints)} clean endpoint(s).")


def rewrite_vless_with_endpoint(vless_link: str, endpoint: str) -> str:
    """Point the vless link at a clean IP:port (drop any hostname/port)."""
    if not vless_link or "vless://" not in vless_link:
        return vless_link
    body = vless_link[len("vless://"):]
    hash_i = body.find("#")
    frag = body[hash_i:] if hash_i >= 0 else ""
    if hash_i >= 0:
        body = body[:hash_i]
    q_i = body.find("?")
    query = body[q_i:] if q_i >= 0 else ""
    if q_i >= 0:
        body = body[:q_i]
    at = body.rfind("@")
    user = body[:at] if at >= 0 else ""
    hostport = body[at + 1:] if at >= 0 else body
    ip, _, port = endpoint.rpartition(":")
    new_hostport = f"{ip}:{port}" if port.isdigit() else endpoint
    return f"vless://{user}@{new_hostport}{query}{frag}"
