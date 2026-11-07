"""Textual TUI — the modern, cross-platform console for the Cloudflare-worker
VPN.  Walks the user 0 → 100:

  1. Welcome
  2. Token (verify + token-permission guide)
  3. Account pick
  4. Worker name + UUID
  5. Deploy (via wrangler, with friendly error explanation + retry)
  6. Get your vless config (press `c` to copy to clipboard)
  7. Done + test guidance

Run:  python -m vpn_console.tui   (or: run.py)
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import (Button, Input, Label, ListItem, ListView, Markdown,
                             ProgressBar, Static)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vpn_console.cf_api import Config, CFError  # noqa: E402
from vpn_console.worker_bundle import (find_worker_js, safe_worker_name,  # noqa: E402
                                       generate_uuid, validate_worker_js)
from vpn_console.vless import VlessProfile  # noqa: E402
from vpn_console.deploy_wrangler import (deploy_wrangler,  # noqa: E402
                                         create_token_instructions,
                                         WranglerMissingError)
from vpn_console.cleanip import find_clean_ips, rewrite_vless_with_endpoint  # noqa: E402
from vpn_console._nav import BackMixin  # noqa: E402

try:
    import pyperclip
except Exception:  # pragma: no cover
    pyperclip = None

STEPS = ["Welcome", "Token", "Account", "Worker", "Deploy", "Config", "Done"]


def run_in_thread(fn, on_success, on_error):
    """Run `fn` on a bg thread, dispatch callbacks on the UI event loop."""

    def _worker():
        try:
            on_success(fn())
        except WranglerMissingError as e:
            on_error(f"[red]✗ {e}[/]")
        except CFError as e:
            on_error(f"[red]✗ {e.title} — {e.detail}[/]\n[yellow]Fix: {e.fix}[/]")
        except Exception as e:  # noqa: BLE001
            on_error(f"[red]✗ {e}[/]")

    threading.Thread(target=_worker, daemon=True).start()


class State:
    token = ""
    accounts: list = []
    account_id = ""
    name = ""
    uuid = ""
    worker_path = None
    host = ""
    prof = None


APP = State()


class WelcomeScreen(BackMixin):
    BINDINGS = [Binding("enter", "start", "Start")]

    def compose(self) -> ComposeResult:
        yield Markdown(
            "# Cloudflare-Worker VPN Console\n\n"
            "A **0 → 100** wizard that creates and controls a Cloudflare-Worker "
            "VLESS proxy right from your terminal.\n\n"
            "**What you'll get**\n"
            "- a deployed `worker` reachable at `https://<name>.<subdomain>.workers.dev`\n"
            "- a ready-to-use `vless://…` config copied to your clipboard\n"
            "- friendly error explanations and fixes at every step\n\n"
            "**Steps**: {}\n\n"
            "> Press Enter to begin.".format(" → ".join(STEPS))
        )
        yield Button("Start", variant="primary", id="start")

    def on_button_pressed(self, event):
        if event.button.id == "start":
            self.app.push_screen("token")


class TokenScreen(BackMixin):
    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Label(f"Step 2/{len(STEPS)} — Cloudflare API token", id="step")
        yield Markdown(create_token_instructions())
        yield Input(placeholder="paste API token", password=True, id="tok")
        yield Button("Verify & continue", variant="primary", id="go")
        yield Static("", id="err")

    def on_button_pressed(self, event):
        if event.button.id == "go":
            self._verify()

    def on_input_submitted(self, event):
        if event.input.id == "tok":
            self._verify()

    def _verify(self):
        tok = self.query_one("#tok", Input).value.strip()
        if not tok:
            self.query_one("#err", Static).update("[red]Token cannot be empty[/]")
            return
        APP.token = tok
        errw = self.query_one("#err", Static)
        errw.update("verifying…")

        def fetch():
            c = Config(tok, timeout=30)
            c.verify_token()
            return c.list_accounts()

        run_in_thread(fetch, self._ok, lambda m: errw.update(m))

    def _ok(self, accounts):
        if not accounts:
            self.query_one("#err", Static).update(
                "[red]No accounts are visible with this token.[/]\n"
                "[yellow]Fix: recreate the token and include Account-Settings:Read.[/]")
            return
        APP.accounts = accounts
        self.app.push_screen("account")


class AccountScreen(BackMixin):
    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Label(f"Step 3/{len(STEPS)} — pick account", id="step")
        yield ListView(id="accs")
        yield Button("Continue", variant="primary", id="go", disabled=True)

    def on_mount(self):
        lv = self.query_one("#accs", ListView)
        for acc in APP.accounts:
            lv.append(ListItem(Label(Config.account_display(Config, acc))))

    def on_list_view_highlighted(self, event):
        if event.item is None:
            return
        idx = self.query_one("#accs", ListView).index
        if idx is not None:
            APP.account_id = APP.accounts[idx]["id"]
            self.query_one("#go", Button).disabled = False

    def on_button_pressed(self, event):
        if event.button.id == "go" and APP.account_id:
            self.app.push_screen("worker")


class WorkerScreen(BackMixin):
    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Label(f"Step 4/{len(STEPS)} — worker name + UUID", id="step")
        yield Markdown(
            "Give the worker a **name** (lowercase letters, digits, hyphens; "
            "max 64 chars). A fresh **UUID** is generated automatically — you can "
            "keep it or paste your own."
        )
        yield Horizontal(
            Input(placeholder="worker name (e.g. my-vpn)", id="nm"),
            Input(placeholder="UUID (auto)", id="uv"),
        )
        yield Static("worker bundle: " + str(APP.worker_path or "auto-detect"), id="wp")
        yield Button("Continue", variant="primary", id="go")

    def on_mount(self):
        self.query_one("#nm", Input).value = APP.name or "vpn-edge"
        self.query_one("#uv", Input).value = APP.uuid or generate_uuid()
        APP.worker_path = find_worker_js()
        self.query_one("#wp", Static).update(
            "worker bundle: " + str(APP.worker_path or "not found — put _worker.js next to the console"))

    def on_button_pressed(self, event):
        if event.button.id == "go":
            APP.name = safe_worker_name(self.query_one("#nm", Input).value)
            APP.uuid = self.query_one("#uv", Input).value.strip() or generate_uuid()
            self.app.push_screen("deploy")


class DeployScreen(BackMixin):
    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Label(f"Step 5/{len(STEPS)} — deploy", id="step")
        yield Markdown("Uploading the worker and setting its UUID.")
        yield ProgressBar(total=100, show_percentage=True, id="pb")
        yield Static("", id="msg")
        yield Button("Deploy now", variant="primary", id="go")

    def on_button_pressed(self, event):
        if event.button.id == "go":
            self._deploy()

    def _deploy(self):
        pb = self.query_one("#pb", ProgressBar)
        msg = self.query_one("#msg", Static)
        pb.update(progress=5)
        msg.update("starting deploy…")
        wp = APP.worker_path or find_worker_js()
        if not wp:
            msg.update("[red]No worker bundle found. Place the edgetunnel _worker.js "
                       "next to the console or pass it via the CLI.[/]")
            return
        ok_v, vmsg = validate_worker_js(wp)
        if not ok_v:
            msg.update(f"[red]{vmsg}[/]")
            return

        def work():
            return deploy_wrangler(APP.token, APP.account_id, APP.name,
                                   str(wp), APP.uuid)

        def ok(res):
            if not res.ok:
                pb.update(progress=0)
                msg.update(f"[red]✗ {res.message}[/]\n[yellow]Fix: see above; press "
                           "Tab to retry.[/]\n" + (res.stderr or "")[-400:])
                return
            APP.host = res.host
            pb.update(progress=100)
            msg.update(f"[green]✔ Deployed. host: {res.host}[/]")
            self.app.push_screen("config")

        run_in_thread(work, ok, lambda m: msg.update(m))


class CleanIPScreen(BackMixin):
    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Label("Find clean Cloudflare IPs (SenPaiScanner)", id="step")
        yield Markdown(
            "This runs SenPaiScanner to probe Cloudflare IPs and validate the "
            "best ones through your deployed worker. It can take a minute or "
            "two (longer in gentle mode).\n\n"
            "When it finishes, you can copy a rewritten `vless://…` link that "
            "points at a clean endpoint."
        )
        yield ProgressBar(total=100, show_percentage=True, id="pb")
        yield Static("", id="msg")
        yield Button("Start scan", variant="primary", id="go")

    def on_button_pressed(self, event):
        if event.button.id == "go":
            self._scan()

    def _scan(self):
        pb = self.query_one("#pb", ProgressBar)
        msg = self.query_one("#msg", Static)
        if APP.prof is None:
            msg.update("[red]No deployed config available — complete the wizard first.[/]")
            return
        link = APP.prof.share_link()
        pb.update(progress=5)
        msg.update("running SenPaiScanner… (this may take a while)")

        def work():
            return find_clean_ips(link, count=800, workers=25, timeout_s=6,
                                  gentle=True, scan_timeout=360)

        def ok(res):
            if not res.ok:
                pb.update(progress=0)
                msg.update(f"[red]✗ {res.message}[/]")
                return
            pb.update(progress=100)
            shown = "\n".join(
                f"  {ep}\n  → {rewrite_vless_with_endpoint(link, ep)}"
                for ep in res.endpoints[:5])
            msg.update(f"[green]✔ {res.message}[/]\n\n{shown}\n\n"
                       f"[yellow](all {len(res.endpoints)} saved to "
                       f"clean-ips.txt)[/]")
            Path("clean-ips.txt").write_text("\n".join(res.endpoints) + "\n")

        run_in_thread(work, ok, lambda m: msg.update(m))


class ConfigScreen(BackMixin):
    BINDINGS = [
        Binding("c", "copy", "Copy config"),
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Label(f"Step 6/{len(STEPS)} — your vless config", id="step")
        yield Markdown("Press **c** (or the button) to copy the share link.")
        yield Static("", id="link")
        yield Static("", id="copied")
        yield Button("Copy to clipboard", variant="primary", id="copy")

    def on_mount(self):
        APP.prof = VlessProfile(uuid=APP.uuid, address=APP.host, name=APP.name)
        self.query_one("#link", Static).update(APP.prof.share_link())

    def on_button_pressed(self, event):
        if event.button.id == "copy":
            self._copy()

    def action_copy(self):
        self._copy()

    def _copy(self):
        if APP.prof is None:
            return
        link = APP.prof.share_link()
        if pyperclip is not None:
            try:
                pyperclip.copy(link)
            except Exception:  # noqa: BLE001
                pass
        self.query_one("#copied", Static).update("[green]✔ Copied to clipboard[/]")


class DoneScreen(BackMixin):
    BINDINGS = [Binding("escape", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        link = APP.prof.share_link() if APP.prof else ""
        yield Label(f"Step 7/{len(STEPS)} — done", id="step")
        yield Markdown(
            "**Your worker is deployed.**\n\n"
            "- Host: `{host}`\n"
            "- UUID: `{uuid}`\n"
            "- vless link (press `c` after up to copy):\n\n"
            "```\n{link}\n```\n\n"
            "**Test without a VPN:** run the `localtest` harness from the "
            "cf-worker-proxy project (start-local-worker.sh → start-xray.sh → "
            "curl --socks5-hostname 127.0.0.1:10808 https://www.google.com).\n\n"
            "> Press Esc to quit."
        ).format(host=APP.host, uuid=APP.uuid, link=link)
        yield Button("Copy vless link", variant="primary", id="copy")

    def on_button_pressed(self, event):
        if event.button.id == "copy" and APP.prof is not None:
            try:
                pyperclip.copy(APP.prof.share_link())
            except Exception:  # noqa: BLE001
                pass

    def action_quit(self):
        self.app.exit()


class CfConsoleApp(App):
    TITLE = "Cloudflare-Worker VPN Console"
    SUB_TITLE = "zero → 100"
    CSS = """
    Screen { padding: 1 2; }
    #step { color: $accent; text-style: bold; margin-bottom: 1; }
    ProgressBar { height: 1; margin: 1 0; }
    Static { margin: 1 0; }
    Button { margin: 1 2 0 0; }
    """

    SCREENS = {
        "welcome": WelcomeScreen,
        "token": TokenScreen,
        "account": AccountScreen,
        "worker": WorkerScreen,
        "deploy": DeployScreen,
        "config": ConfigScreen,
        "done": DoneScreen,
    }

    BINDINGS = [Binding("ctrl+q", "quit", "Quit")]

    def on_mount(self):
        self.push_screen("welcome")


def main():
    CfConsoleApp().run()


if __name__ == "__main__":
    main()
