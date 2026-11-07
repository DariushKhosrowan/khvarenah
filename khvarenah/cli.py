"""Headless CLI for Khvarenah.  Cross-platform (Linux/Windows).

Purpose: drive the whole zero→100 workflow from a terminal without the TUI:
    python cli.py check [token]
    python cli.py deploy --token X --name NAME [--uuid U] [--worker path]
    python cli.py config --token X --name NAME --uuid U [--address H] [--port N]
                         [--security tls|none] [--path P]
    python cli.py status --token X [--account A]
    python cli.py upgrade            # self-update from GitHub
    python cli.py clean --token X --name NAME --uuid U   # find clean IP
    python cli.py autopilot --token X --name NAME   # deploy + find clean IP
    python cli.py history            # list saved vless configs (and tokens)
    python cli.py version
Exit codes: 0 ok, 1 user/validation error, 2 CF error (message printed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from khvarenah.cf_api import Config, CFError  # noqa: E402
from khvarenah import worker_bundle as wb  # noqa: E402
from khvarenah.vless import VlessProfile  # noqa: E402
from khvarenah.deploy_wrangler import deploy_wrangler  # noqa: E402
from khvarenah.cleanip import (find_clean_ips,  # noqa: E402
                                 rewrite_vless_with_endpoint)
from khvarenah.updater import (current_version, is_update_available,  # noqa: E402
                                apply_update)
from khvarenah import store  # noqa: E402

VERSION = current_version()


def _token(arg: str) -> str:
    if not arg:
        p = Path.home() / ".khvarenah" / "token"
        if p.exists():
            return p.read_text().strip()
        saved = store.get_token()
        if saved:
            return saved
        print("No token provided. Pass --token <CF_API_TOKEN> or save it to ~/.khvarenah/token",
              file=sys.stderr)
        sys.exit(1)
    store.save_token(arg.strip())
    return arg.strip()


def _print_dict(label: str, d: dict) -> None:
    print(f"\n== {label} ==")
    print(json.dumps(d, indent=2, ensure_ascii=False))


def cmd_version(_) -> int:
    print(f"khvarenah {VERSION}")
    return 0


def cmd_check(a) -> int:
    tok = _token(a.token)
    c = Config(tok)
    try:
        r = c.verify_token()
        ok = r.get("success")
        print("Token valid." if ok else "Token status: NOT valid")
        accs = c.list_accounts()
        if not accs:
            print("No accounts found for this token.")
            return 1
        for acc in accs:
            print("  account:", c.account_display(acc))
        # worker file check
        wp = wb.find_worker_js(a.worker)
        if wp:
            ok2, msg = wb.validate_worker_js(wp)
            print(f"\nWorker bundle: {wp}")
            print(f"  {msg}")
        else:
            print("\nWorker bundle: NOT FOUND (use --worker to point at _worker.js)")
        return 0 if ok else 1
    except CFError as e:
        print(f"[error] {e}")
        print(f"[fix]   {e.fix}")
        return 2


def cmd_deploy(a) -> int:
    tok = _token(a.token)
    c = Config(tok)
    name = wb.safe_worker_name(a.name)
    worker_path = wb.find_worker_js(a.worker)
    if not worker_path:
        print("[error] Could not find worker bundle. Use --worker to point at the edgetunnel _worker.js.")
        return 1
    ok, msg = wb.validate_worker_js(worker_path)
    if not ok:
        print(f"[error] Worker bundle invalid: {msg}")
        return 1
    try:
        accs = c.list_accounts()
        acc = (a.account or accs[0]["id"]) if accs else ""
        if not acc:
            print("[error] No account id available. Pass --account.")
            return 1
        print(f"Deploying '{name}' to account {acc} ...")
        uuid = a.uuid or wb.generate_uuid()
        result = deploy_wrangler(tok, acc, name, str(worker_path), uuid)
        if not result.ok:
            print(f"[error] {result.message}")
            if result.stderr:
                print(result.stderr[-500:])
            return 2
        host = result.host
        print("Deploy OK.")
        print(f"  UUID: {uuid}")
        print(f"  worker host: {host}")
        prof = VlessProfile(uuid=uuid, address=host, name=a.name or name)
        store.remember_vless(prof)
        print(f"  vless link:\n    {prof.share_link()}")
        return 0
    except CFError as e:
        print(f"[error] {e}")
        print(f"[fix]   {e.fix}")
        return 2


def cmd_config(a) -> int:
    tok = _token(a.token)
    c = Config(tok)
    try:
        accs = c.list_accounts()
        acc = (a.account or accs[0]["id"]) if accs else ""
        name = wb.safe_worker_name(a.name)
        sub = c.get_subdomain(acc) if acc else ""
        default_host = f"{name}.{sub}.workers.dev" if sub else f"{name}.workers.dev"
        address = a.address or default_host
        uuid = a.uuid or ""
        prof = VlessProfile(uuid=uuid, address=address, port=a.port,
                            security=a.security, path=a.path, name=a.name or name)
        store.remember_vless(prof)
        print("\n=== YOUR vless CONFIG ===")
        print("Share link:")
        print("  " + prof.share_link())
        print("\nxray client json (also saved to client-xray.json):")
        Path("client-xray.json").write_text(prof.xray_client_json())
        print("  saved client-xray.json")
        print("\nCompatibility note: for local (no-VPN) testing use --security none "
              "and point --address at your machine's LAN IP on port 8787.")
        return 0
    except CFError as e:
        print(f"[error] {e}")
        print(f"[fix]   {e.fix}")
        return 2


def cmd_status(a) -> int:
    tok = _token(a.token)
    c = Config(tok)
    try:
        accs = c.list_accounts()
        if not accs:
            print("No accounts found.")
            return 1
        acc = a.account or accs[0]["id"]
        scripts = c.list_scripts(acc)
        print(f"Account {acc} — {len(scripts)} worker script(s):")
        for s in scripts:
            print(f"  - {s.get('id')} (created {s.get('created_on','')[:19]})")
        return 0
    except CFError as e:
        print(f"[error] {e}")
        print(f"[fix]   {e.fix}")
        return 2


def cmd_scan(a) -> int:
    """Find clean IPs for a deployed worker via SenPaiScanner."""
    tok = _token(a.token)
    c = Config(tok)
    try:
        accs = c.list_accounts()
        acc = (a.account or accs[0]["id"]) if accs else ""
        name = wb.safe_worker_name(a.name)
        sub = c.get_subdomain(acc) if acc else ""
        default_host = f"{name}.{sub}.workers.dev" if sub else f"{name}.workers.dev"
        address = a.address or default_host
        uuid = a.uuid or ""
        if not uuid:
            # ask user for uuid, or require it
            print("[error] --uuid required to build the vless config for scanning.")
            return 1
        prof = VlessProfile(uuid=uuid, address=address, port=a.port,
                            security=a.security, path=a.path, name=a.name or name)
        link = prof.share_link()
        print(f"Scanning for clean IPs against {address} …")
        print("  (this runs SenPaiScanner; may take a minute or two)")
        r = find_clean_ips(link, count=a.count, workers=a.workers,
                           timeout_s=a.timeout, gentle=a.gentle, ports=a.ports,
                           scan_timeout=a.scan_timeout)
        if not r.ok:
            print(f"[error] {r.message}")
            return 2
        print(f"\n=== {r.message} ===")
        for ep in r.endpoints[:a.top]:
            print("  " + ep)
            print("  → " + rewrite_vless_with_endpoint(link, ep))
        Path("clean-ips.txt").write_text("\n".join(r.endpoints) + "\n")
        print(f"\nAll endpoints saved to clean-ips.txt ({len(r.endpoints)} total).")
        return 0
    except CFError as e:
        print(f"[error] {e}")
        print(f"[fix]   {e.fix}")
        return 2


def cmd_clean(a) -> int:
    """Find a clean IP for a deployed worker, then emit a working vless link."""
    tok = _token(a.token)
    c = Config(tok)
    try:
        accs = c.list_accounts()
        acc = (a.account or accs[0]["id"]) if accs else ""
        name = wb.safe_worker_name(a.name)
        sub = c.get_subdomain(acc) if acc else ""
        default_host = f"{name}.{sub}.workers.dev" if sub else f"{name}.workers.dev"
        address = a.address or default_host
        uuid = a.uuid or ""
        if not uuid:
            print("[error] --uuid required to build the vless config for scanning.")
            return 1
        prof = VlessProfile(uuid=uuid, address=address, port=a.port,
                            security=a.security, path=a.path, name=a.name or name)
        link = prof.share_link()
        print(f"Scanning for clean IPs against {address} …")
        r = find_clean_ips(link, count=a.count, workers=a.workers,
                           timeout_s=a.timeout, gentle=a.gentle, ports=a.ports,
                           scan_timeout=a.scan_timeout)
        if not r.ok:
            print(f"[error] {r.message}")
            return 2
        top = max(1, getattr(a, "top", 5))
        eps = r.endpoints[:top]
        configs = []
        for ep in eps:
            working_link = rewrite_vless_with_endpoint(link, ep)
            ip, _, port = ep.rpartition(":")
            store.remember_vless(
                VlessProfile(uuid=uuid, address=ip,
                             port=int(port) if port.isdigit() else 443,
                             name=(a.name or name) + " (clean IP)"),
                clean_ip=True,
            )
            configs.append((ep, working_link))
        best_ep, best_link = configs[0]
        print(f"\n✓ Best clean IP: {best_ep}")
        print(f"  Working vless link:\n    {best_link}")
        if len(configs) > 1:
            print(f"\nMore clean IPs ({len(configs)} total):")
            for ep, link in configs[1:]:
                print(f"  • {ep}\n    {link}")
        Path("clean-ips.txt").write_text("\n".join(r.endpoints) + "\n")
        Path("clean-configs.txt").write_text(
            "\n\n".join(f"# {ep}\n{link}" for ep, link in configs) + "\n")
        print(f"\nSaved endpoints → clean-ips.txt · {len(configs)} configs → clean-configs.txt")
        return 0
    except CFError as e:
        print(f"[error] {e}")
        print(f"[fix]   {e.fix}")
        return 2


def cmd_autopilot(a) -> int:
    """Deploy, then find a clean IP and emit a working vless link."""
    rc = cmd_deploy(a)
    if rc != 0:
        return rc
    return cmd_clean(a)


def cmd_upgrade(a) -> int:
    """Check for / apply the latest GitHub release."""
    print(f"Current version: {VERSION}")
    ok, rel = is_update_available()
    if not ok:
        print("You're already on the latest version.")
        return 0
    print(f"Update available: {rel['tag']} — downloading & installing …")
    done, msg = apply_update()
    print(msg)
    return 0 if done else 1


def cmd_history(a) -> int:
    """List saved vless configs (and tokens) from memory."""
    entries = store.list_vless()
    print(f"🧠 Saved vless configs: {len(entries)}")
    for i, r in enumerate(entries, 1):
        tag = "clean-IP" if r.get("clean_ip") else "workers.dev"
        print(f"  {i}. {r.get('name') or r.get('address')} [{tag}] — "
              f"{r.get('ts')}")
        print(f"     {r.get('link')}")
    tokens = store.stored_tokens()
    if tokens:
        show = getattr(a, "show_tokens", False)
        print(f"\n🔑 Saved tokens: {len(tokens)}")
        for label in tokens:
            if show:
                print(f"  • {label}: {tokens[label]['token']}")
            else:
                print(f"  • {label}: •••• (use --show-tokens to reveal)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="khvarenah",
                                description="Khvarenah — Cloudflare-worker VLESS VPN console (headless)")
    p.add_argument("--version", action="store_true", help="show version and exit")
    sub = p.add_subparsers(dest="cmd")
    for name, help_ in [("check", "verify token + worker bundle"),
                        ("deploy", "deploy worker + set UUID"),
                        ("config", "generate vless config/link"),
                        ("status", "list deployed workers"),
                        ("scan", "find clean IPs via SenPaiScanner"),
                        ("clean", "find a clean IP and emit a working vless link"),
                        ("autopilot", "deploy then find a clean IP (full auto)"),
                        ("upgrade", "self-update from the latest GitHub release"),
                        ("history", "list saved vless configs and tokens")]:
        sp = sub.add_parser(name, help=help_)
        if name == "history":
            sp.add_argument("--show-tokens", action="store_true",
                            help="reveal stored API tokens")
        sp.add_argument("--token")
        sp.add_argument("--account")
        sp.add_argument("--worker")
        sp.add_argument("--name")
        sp.add_argument("--uuid")
        sp.add_argument("--address")
        sp.add_argument("--port", type=int, default=443)
        sp.add_argument("--security", choices=["tls", "none"], default="tls")
        sp.add_argument("--path", default="/")
        sp.add_argument("--count", type=int, default=2000)
        sp.add_argument("--workers", type=int, default=25)
        sp.add_argument("--timeout", type=int, default=8)
        sp.add_argument("--top", type=int, default=10)
        sp.add_argument("--ports", default="443")
        sp.add_argument("--gentle", action="store_true", default=True)
        sp.add_argument("--scan-timeout", type=int, default=600)
    return p


def main(argv=None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    if args.version:
        return cmd_version(args)
    if not args.cmd:
        p.print_help()
        return 0
    fn = {"check": cmd_check, "deploy": cmd_deploy,
          "config": cmd_config, "status": cmd_status,
          "scan": cmd_scan, "clean": cmd_clean,
          "autopilot": cmd_autopilot, "upgrade": cmd_upgrade,
          "history": cmd_history}[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
