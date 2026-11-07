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
from khvarenah.updater import (current_version, check_and_apply)  # noqa: E402
from khvarenah import store  # noqa: E402
from khvarenah.stealth import boundary_pause, enabled as stealth_enabled  # noqa: E402

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


def _resolve_account(c, requested: str) -> tuple[str, dict]:
    """Return (account_id, account_dict), remembering accounts for reuse."""
    accs = c.list_accounts()
    if not accs:
        raise CFError("No accounts", "This token has no Cloudflare accounts.",
                      "Create an account or use a token scoped to one.")
    acc = None
    if requested:
        for a in accs:
            if a.get("id") == requested or a.get("name") == requested:
                acc = a
                break
        if acc is None:
            raise CFError("Account not found",
                          f"No account matches '{requested}'.",
                          "List accounts with: khvarenah check")
    else:
        # Default to the account the user last marked active (or the first).
        active = store.active_account()
        acc = next((a for a in accs if a.get("id") == active), accs[0])
    aid = acc.get("id", "")
    sub = ""
    try:
        sub = c.get_subdomain(aid)
    except CFError:
        sub = ""
    store.remember_account(aid, acc.get("name", ""), sub)
    return aid, acc


def _client_and_account(a):
    """Build a Config using the right token for the target account.

    Resolution order:
      1. If the user requested a specific account (or an active account is
         set), use that account's per-account token if one was saved.
      2. Otherwise fall back to the default token.
    Returns (client, account_id, account_info).
    """
    target = getattr(a, "account", "") or store.active_account()
    tok = store.get_account_token(target) if target else None
    if not tok:
        tok = _token(getattr(a, "token", ""))
    c = Config(tok)
    acc, acc_info = _resolve_account(c, target or getattr(a, "account", ""))
    return c, acc, acc_info


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
            store.remember_account(acc.get("id", ""), acc.get("name", ""))
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
    try:
        c, acc, acc_info = _client_and_account(a)
        # Autopilot / default: derive the worker name from the account name,
        # never a "vpn" label, and never require the user to type one.
        name = wb.safe_worker_name(a.name or wb.worker_name_from_account(acc_info))
        worker_path = wb.find_worker_js(a.worker)
        if not worker_path:
            print("[error] Could not find worker bundle. Use --worker to point at the edgetunnel _worker.js.")
            return 1
        ok, msg = wb.validate_worker_js(worker_path)
        if not ok:
            print(f"[error] Worker bundle invalid: {msg}")
            return 1
        print(f"Deploying '{name}' to account {store.account_label(acc)} ...")
        uuid = a.uuid or wb.generate_uuid()
        result = deploy_wrangler(c.token, acc, name, str(worker_path), uuid)
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
    try:
        c, acc, acc_info = _client_and_account(a)
        scripts = c.list_scripts(acc)
        print(f"Account {store.account_label(acc)} ({acc}) — {len(scripts)} worker script(s):")
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
    """Find a clean IP for a deployed worker, then emit working vless links."""
    try:
        c, acc, acc_info = _client_and_account(a)
        name = wb.safe_worker_name(a.name or wb.worker_name_from_account(acc_info))
        sub = store.get_account(acc).get("subdomain") or c.get_subdomain(acc)
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
        total = len(r.endpoints)
        if getattr(a, "all", False):
            top = total
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
                note=f"worker={name} host={address}",
            )
            configs.append((ep, working_link))
        best_ep, best_link = configs[0]
        print(f"\n✓ Best clean IP: {best_ep}")
        print(f"  Working vless link:\n    {best_link}")
        if len(configs) > 1:
            print(f"\nMore clean IPs ({len(configs)} total):")
            for ep, link in configs[1:]:
                print(f"  • {ep}\n    {link}")
        # Offer more if the user wants (only when attached to a terminal).
        if total > top and sys.stdin.isatty():
            try:
                ans = input(f"\n{total} clean IPs found — generate configs for "
                            f"all of them? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            if ans in ("y", "yes"):
                extra = r.endpoints[top:]
                for ep in extra:
                    working_link = rewrite_vless_with_endpoint(link, ep)
                    ip, _, port = ep.rpartition(":")
                    store.remember_vless(
                        VlessProfile(uuid=uuid, address=ip,
                                     port=int(port) if port.isdigit() else 443,
                                     name=(a.name or name) + " (clean IP)"),
                        clean_ip=True, note=f"worker={name} host={address}",
                    )
                    configs.append((ep, working_link))
                print(f"  ✚ added {len(extra)} more configs (now {len(configs)} total).")
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
    try:
        c, acc, acc_info = _client_and_account(a)
        name = wb.safe_worker_name(a.name or wb.worker_name_from_account(acc_info))
        uuid = a.uuid or wb.generate_uuid()
        # Deploy (threading the same UUID into clean so scanning has a config).
        import copy
        d = copy.copy(a)
        d.token = c.token
        d.account = acc
        d.name = name
        d.uuid = uuid
        rc = cmd_deploy(d)
        if rc != 0:
            return rc
        # Pause between stages — a human reads the deploy output, thinks, and
        # then moves on to scanning.  Avoids back-to-back API bursts.
        if stealth_enabled():
            boundary_pause(1.0, 4.0)
        d2 = copy.copy(d)
        return cmd_clean(d2)
    except CFError as e:
        print(f"[error] {e}")
        print(f"[fix]   {e.fix}")
        return 2


def cmd_upgrade(a) -> int:
    """Check for / apply the latest GitHub release."""
    print(f"Current version: {VERSION}")
    done, msg = check_and_apply()
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
    accs = store.list_accounts()
    if accs:
        print(f"\n☁️ Saved accounts: {len(accs)}")
        for aid, info in accs.items():
            print(f"  • {info.get('name') or aid} ({aid})"
                  + (f" · {info['subdomain']}.workers.dev" if info.get("subdomain") else ""))
    return 0


def cmd_usage(a) -> int:
    """Show daily request usage for the active account's workers."""
    try:
        c, acc, acc_info = _client_and_account(a)
        scripts = c.list_scripts(acc)
        if not scripts:
            print(f"Account {store.account_label(acc)} has no worker scripts yet.")
            return 0
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc)
        since = (now - _dt.timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
        until = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"Daily request usage — {store.account_label(acc)} ({acc}) "
              f"(since {since[:10]}):")
        total = 0
        for s in scripts[:20]:
            sid = s.get("id") or s.get("name") or ""
            if not sid:
                continue
            data = c.script_analytics(acc, sid, since=since, until=until)
            count = (data or {}).get("requestCount", 0)
            total += int(count or 0)
            print(f"  • {sid:<30} {count:>12,} requests")
        print(f"\n  TOTAL: {total:,} requests in the last 24h")
        return 0
    except CFError as e:
        print(f"[error] {e}")
        print(f"[fix]   {e.fix}")
        return 2


def cmd_accounts(a) -> int:
    """List saved accounts, add a new one, or switch the active account."""
    # Add a new account: verify the token and remember its account(s).
    if getattr(a, "add", None):
        tok = _token(a.add)
        c = Config(tok)
        try:
            r = c.verify_token()
            if not r.get("success"):
                print("[error] Token could not be verified.")
                return 2
            accs = c.list_accounts()
            if not accs:
                print("[error] This token has no Cloudflare accounts.")
                return 2
            # save the token under each account id + as default if none yet
            stored = store.stored_tokens()
            for acc in accs:
                aid = acc.get("id", "")
                store.remember_account(aid, acc.get("name", ""))
                store.save_token(tok, aid)
            if not stored:
                store.save_token(tok, "default")
            # switch active to the first added account
            first = accs[0].get("id", "")
            if first:
                store.set_active_account(first)
            print(f"✓ Added {len(accs)} account(s) from this token:")
            for acc in accs:
                aid = acc.get("id", "")
                marker = "★ " if aid == store.active_account() else "  "
                print(f"{marker}{acc.get('name')} ({aid})")
            return 0
        except CFError as e:
            print(f"[error] {e}")
            print(f"[fix]   {e.fix}")
            return 2

    accs = store.list_accounts()
    if not accs:
        print("No saved accounts yet. Add one:")
        print("  khvarenah accounts --add <CF_API_TOKEN>")
        return 0
    # Switch the active (default) account if requested.
    switch = getattr(a, "set", "")
    if switch:
        if switch not in accs:
            print(f"No saved account '{switch}'. Use its account ID or name from the list below.")
            return 1
        if store.set_active_account(switch):
            print(f"✓ Active account set to: {store.account_label(switch)} ({switch})")
            return 0
    active = store.active_account()
    print(f"☁️ Saved accounts: {len(accs)}")
    for aid, info in accs.items():
        marker = "★ " if aid == active else "  "
        tok_mark = " 🔑" if store.get_account_token(aid) else ""
        print(f"{marker}{info.get('name') or aid} ({aid})"
              + (f" · {info['subdomain']}.workers.dev" if info.get("subdomain") else "")
              + tok_mark
              + ("  [active]" if aid == active else ""))
    print("\nSwitch accounts:  khvarenah accounts --set <account-id>")
    print("Add an account:  khvarenah accounts --add <CF_API_TOKEN>")
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
                        ("usage", "show daily request usage for your active account"),
                        ("history", "list saved vless configs and tokens"),
                        ("accounts", "list or switch saved Cloudflare accounts")]:
        sp = sub.add_parser(name, help=help_)
        if name == "history":
            sp.add_argument("--show-tokens", action="store_true",
                            help="reveal stored API tokens")
        if name == "accounts":
            sp.add_argument("--set", metavar="ACCOUNT_ID",
                            help="switch the active (default) account")
            sp.add_argument("--add", metavar="CF_API_TOKEN",
                            help="verify a token and add its account(s)")
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
        sp.add_argument("--all", action="store_true",
                        help="generate configs for every clean IP found (default: --top only)")
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
          "usage": cmd_usage,
          "history": cmd_history, "accounts": cmd_accounts}[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
