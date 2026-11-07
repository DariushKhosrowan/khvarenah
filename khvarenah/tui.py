"""Textual TUI — the modern, cross-platform console for the Cloudflare-worker
VPN.  Walks the user 0 → 100:

  1. Welcome (Start / ⚡ Autopilot)
  2. Token (verify + token-permission guide)
  3. Account pick
  4. Worker name + UUID
  5. Deploy (via wrangler, with friendly error explanation + retry)
  6. Get your vless config (press `c` to copy to clipboard)
  7. Done + test guidance

Autopilot: paste the token once and it runs 2→6 for you (picks an account,
names the worker, deploys, finds a clean IP, and shows a working vless link).

Run:  python -m khvarenah.tui   (or: khvarenah)
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Container
from textual.screen import Screen
from textual.widgets import (Button, Input, Label, ListItem, ListView, Markdown,
                             ProgressBar, Static)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from khvarenah.i18n import tr, set_lang  # noqa: E402
from khvarenah.cf_api import Config, CFError  # noqa: E402
from khvarenah.worker_bundle import (find_worker_js, safe_worker_name,  # noqa: E402
                                       generate_uuid, validate_worker_js,
                                       default_worker_name, worker_name_from_account)
from khvarenah.vless import VlessProfile  # noqa: E402
from khvarenah.deploy_wrangler import (deploy_wrangler,  # noqa: E402
                                         create_token_instructions,
                                         WranglerMissingError)
from khvarenah.cleanip import find_clean_ips, rewrite_vless_with_endpoint  # noqa: E402
from khvarenah._nav import BackMixin  # noqa: E402
from khvarenah.banner import rich_banner  # noqa: E402
from khvarenah import store  # noqa: E402

try:
    import pyperclip
except Exception:  # pragma: no cover
    pyperclip = None

STEPS_KEYS = ["welcome", "token", "account", "worker", "deploy", "config", "done"]


def _steps() -> list:
    return [
        tr("welcome.title"), tr("token.title"), tr("account.title"), tr("worker.title"),
        tr("deploy.title"), tr("config.title"), tr("done.title"),
    ]


STEPS = _steps()


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
    prof: "VlessProfile | None" = None
    autopilot = False
    last_error = ""


APP = State()


def _restore_prof() -> bool:
    """Restore the last saved deployment into APP.prof if not already set."""
    if APP.prof is not None:
        return True
    rec = store.last_vless()
    if not rec or not rec.get("address"):
        return False
    APP.prof = VlessProfile(
        uuid=rec.get("uuid", "") or "",
        address=rec["address"],
        port=int(rec.get("port") or 443),
        name=rec.get("name") or "cf-worker-edge",
    )
    if not APP.uuid:
        APP.uuid = getattr(APP.prof, "uuid", "")
    if not APP.host:
        APP.host = APP.prof.address
    if not APP.name:
        APP.name = APP.prof.name
    return True


class WelcomeScreen(BackMixin):
    BINDINGS = [Binding("enter", "start", "Start")]

    def compose(self) -> ComposeResult:
        yield Static(rich_banner(54), id="logo")
        yield Markdown(
            tr("welcome.body", steps=" → ".join(_steps())),
            id="welcome_md",
        )
        yield Markdown(tr("welcome.autopilot.body"), id="autopilot_md")
        yield Horizontal(
            Button(tr("welcome.start"), variant="primary", id="start"),
            Button(tr("welcome.autopilot"), variant="success", id="autopilot"),
        )

    def on_button_pressed(self, event):
        if event.button.id == "start":
            self.app.push_screen("token")
        elif event.button.id == "autopilot":
            APP.autopilot = True
            self.app.push_screen("token")


class TokenScreen(BackMixin):
    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Label(tr("step", n=2, total=len(STEPS), name=tr("token.title")), id="step")
        if APP.autopilot:
            yield Label(tr("autopilot.label"), id="ap_label")
        yield Markdown(create_token_instructions())
        yield Input(placeholder=tr("token.placeholder"), password=True, id="tok")
        yield Horizontal(
            Button(tr("token.verify"), variant="primary", id="go"),
            Button(tr("back"), id="back"),
        )
        yield Static("", id="err")

    def on_button_pressed(self, event):
        if event.button.id == "go":
            self._verify()
        elif event.button.id == "back":
            self.app.pop_screen()

    def on_input_submitted(self, event):
        if event.input.id == "tok":
            self._verify()

    def _verify(self):
        tok = self.query_one("#tok", Input).value.strip()
        if not tok:
            self.query_one("#err", Static).update(tr("token.empty"))
            return
        APP.token = tok
        store.save_token(tok)
        errw = self.query_one("#err", Static)
        errw.update(tr("token.working"))

        def fetch():
            c = Config(tok, timeout=30)
            c.verify_token()
            return c.list_accounts()

        run_in_thread(fetch, self._ok, lambda m: errw.update(m))

    def _ok(self, accounts):
        if not accounts:
            self.query_one("#err", Static).update(tr("token.none"))
            return
        APP.accounts = accounts
        self.app.push_screen("account")


class AccountScreen(BackMixin):
    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Label(tr("step", n=3, total=len(STEPS), name=tr("account.title")), id="step")
        if APP.autopilot:
            yield Label(tr("autopilot.label"), id="ap_label")
        yield ListView(id="accs")
        yield Button(tr("account.continue"), variant="primary", id="go", disabled=True)

    def on_mount(self):
        lv = self.query_one("#accs", ListView)
        for acc in APP.accounts:
            lv.append(ListItem(Label(Config.account_display(Config, acc))))
        if APP.autopilot and APP.accounts:
            # pick the first account automatically and continue
            APP.account_id = APP.accounts[0]["id"]
            if not APP.name:
                APP.name = worker_name_from_account(APP.accounts[0])
            lv.index = 0
            self.query_one("#go", Button).disabled = False
            self.app.call_after_refresh(self._auto_continue)

    def _auto_continue(self):
        if APP.account_id:
            self.app.push_screen("worker")

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
        yield Label(tr("step", n=4, total=len(STEPS), name=tr("worker.title")), id="step")
        if APP.autopilot:
            yield Label(tr("autopilot.label"), id="ap_label")
        yield Markdown(tr("worker.body"))
        yield Horizontal(
            Input(placeholder=tr("worker.name_ph"), id="nm"),
            Input(placeholder=tr("worker.uuid_ph"), id="uv"),
        )
        yield Static("worker bundle: " + str(APP.worker_path or "auto-detect"), id="wp")
        yield Horizontal(
            Button(tr("worker.continue"), variant="primary", id="go"),
            Button(tr("back"), id="back"),
        )

    def on_mount(self):
        self.query_one("#nm", Input).value = APP.name or default_worker_name()
        self.query_one("#uv", Input).value = APP.uuid or generate_uuid()
        APP.worker_path = find_worker_js()
        self.query_one("#wp", Static).update(
            "worker bundle: " + str(APP.worker_path or "not found — put _worker.js next to the console"))
        if APP.autopilot:
            APP.name = safe_worker_name(self.query_one("#nm", Input).value)
            APP.uuid = self.query_one("#uv", Input).value.strip() or generate_uuid()
            self.app.call_after_refresh(self._auto_continue)

    def _auto_continue(self):
        self.app.push_screen("deploy")

    def on_button_pressed(self, event):
        if event.button.id == "go":
            APP.name = safe_worker_name(self.query_one("#nm", Input).value)
            APP.uuid = self.query_one("#uv", Input).value.strip() or generate_uuid()
            self.app.push_screen("deploy")
        elif event.button.id == "back":
            self.app.pop_screen()


class DeployScreen(BackMixin):
    BINDINGS = [
        Binding("c", "copy_error", "Copy error"),
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Label(tr("step", n=5, total=len(STEPS), name=tr("deploy.title")), id="step")
        if APP.autopilot:
            yield Label(tr("autopilot.label"), id="ap_label")
        yield Markdown(tr("deploy.body"))
        yield ProgressBar(total=100, show_percentage=True, id="pb")
        yield Static("", id="msg")
        yield Horizontal(
            Button(tr("deploy.btn"), variant="primary", id="go"),
            Button(tr("back"), id="back"),
        )

    def on_button_pressed(self, event):
        if event.button.id == "go":
            self._deploy()
        elif event.button.id == "back":
            self.app.pop_screen()

    def on_mount(self):
        if APP.autopilot:
            self._deploy()

    def _deploy(self):
        pb = self.query_one("#pb", ProgressBar)
        msg = self.query_one("#msg", Static)
        pb.update(progress=5)
        msg.update(tr("deploy.starting"))
        wp = APP.worker_path or find_worker_js()
        if not wp:
            msg.update("[red]No worker bundle found. Place the edgetunnel _worker.js "
                       "next to the console or pass it via the CLI.[/]")
            if APP.autopilot:
                self.app.pop_screen()
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
                APP.last_error = (res.message + "\n" + (res.stderr or "")).strip()
                msg.update(f"[red]✗ {res.message}[/]\n[yellow]Press [b]c[/] to copy the error, Tab to retry.[/]\n"
                           + "```text\n" + APP.last_error[-400:] + "\n```")
                return
            APP.host = res.host
            pb.update(progress=100)
            msg.update(tr("deploy.done", host=res.host))
            self.app.push_screen("config")

        run_in_thread(work, ok, lambda m: msg.update(m))

    def action_copy_error(self):
        err = APP.last_error
        if not err:
            self.notify("No error to copy yet", severity="warning")
            return
        if pyperclip is not None:
            try:
                pyperclip.copy(err)
                self.notify("Error copied to clipboard", severity="information")
                return
            except Exception:  # noqa: BLE001
                pass
        # fallback: show a selectable snippet the user can copy manually
        self.query_one("#msg", Static).update(
            f"[yellow]Copy the error below (select with mouse):[/]\n"
            + "```text\n" + err + "\n```")


class CleanIPScreen(BackMixin):
    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Label(tr("cleanip.title"), id="step")
        yield Markdown(tr("cleanip.body"))
        yield ProgressBar(total=100, show_percentage=True, id="pb")
        yield Static("", id="msg")
        yield Button(tr("cleanip.btn"), variant="primary", id="go")

    def on_mount(self):
        if APP.autopilot:
            self.app.call_after_refresh(self._scan)

    def on_button_pressed(self, event):
        if event.button.id == "go":
            self._scan()

    def _scan(self):
        pb = self.query_one("#pb", ProgressBar)
        msg = self.query_one("#msg", Static)
        _restore_prof()
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
                if APP.autopilot:
                    self.app.call_after_refresh(self._finish)
                return
            pb.update(progress=100)
            eps = res.endpoints[:5]
            shown = "\n".join(
                f"  {ep}\n  → {rewrite_vless_with_endpoint(link, ep)}"
                for ep in eps)
            msg.update(f"[green]✔ {res.message}[/]\n\n{shown}\n\n"
                       f"[yellow](all {len(res.endpoints)} saved to "
                       f"clean-ips.txt)[/]")
            Path("clean-ips.txt").write_text("\n".join(res.endpoints) + "\n")
            if APP.autopilot and eps:
                # autopilot: commit the working clean-IP link and finish
                host, _, port = eps[0].rpartition(":")
                APP.prof = VlessProfile(
                    uuid=APP.uuid, address=host, port=int(port) if port.isdigit() else 443,
                    name=APP.name + " (clean IP)",
                )
                store.remember_vless(APP.prof, clean_ip=True)
                self.app.call_after_refresh(self._finish)

        run_in_thread(work, ok, lambda m: msg.update(m))

    def _finish(self):
        self.app.push_screen("done")


class ConfigScreen(BackMixin):
    BINDINGS = [
        Binding("c", "copy", "Copy config"),
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Label(tr("step", n=6, total=len(STEPS), name=tr("config.title")), id="step")
        yield Markdown(tr("config.body"))
        yield Static("", id="link")
        yield Static("", id="copied")
        yield Button(tr("config.copy"), variant="primary", id="copy")

    def on_mount(self):
        APP.prof = VlessProfile(uuid=APP.uuid, address=APP.host, name=APP.name)
        store.remember_vless(APP.prof)
        self.query_one("#link", Static).update(APP.prof.share_link())
        if APP.autopilot:
            self.app.call_after_refresh(self._auto_continue)

    def _auto_continue(self):
        self._copy()
        self.app.push_screen("cleanip")  # autopilot → find a clean IP

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
        self.query_one("#copied", Static).update(tr("config.copied"))


class DoneScreen(BackMixin):
    BINDINGS = [Binding("escape", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        link = APP.prof.share_link() if APP.prof else ""
        yield Label(tr("step", n=7, total=len(STEPS), name=tr("done.title")), id="step")
        yield Markdown(
            (
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
        )
        yield Button(tr("done.copy"), variant="primary", id="copy")

    def on_button_pressed(self, event):
        if event.button.id == "copy" and APP.prof is not None:
            try:
                pyperclip.copy(APP.prof.share_link())
            except Exception:  # noqa: BLE001
                pass

    def action_quit(self):
        self.app.exit()


class CfConsoleApp(App):
    TITLE = tr("app.title")
    SUB_TITLE = tr("app.subtitle")
    CSS = """
    Screen { padding: 1 2; background: #0f0d09; }
    #step {
      color: #d9b45c; text-style: bold; margin-bottom: 1;
    }
    #ap_label {
      color: #17130b; text-style: bold; margin-bottom: 1;
      background: #e8c266; padding: 0 1; text-align: center;
      border: round #d9b45c; border-title-align: center;
    }
    #logo { color: #e8c266; text-style: bold; margin-bottom: 1; }
    #welcome_md, #autopilot_md { margin: 0 0 1 0; }
    Markdown { color: #b7a984; }
    MarkdownH1 { color: #f1e5c6; text-style: bold; }
    MarkdownH2 { color: #f0d27e; text-style: bold; }
    MarkdownBullet { color: #d9b45c; }

    Static { margin: 1 0; }
    Button {
      margin: 1 2 0 0;
      background: #2a2317; color: #d9c58a;
      border: tall #3a3222;
      padding: 0 3;
    }
    Button:hover { background: #362d1d; color: #e8c266; border: tall #6b5a2e; }
    Button.primary {
      background: #d9b45c; color: #17130b;
      border: tall #d9b45c;
    }
    Button.primary:hover { background: #e8c266; border: tall #e8c266; }
    Button.success { background: #7fbf8a; color: #0f0d09; border: tall #7fbf8a; }

    Input {
      background: #15120c; color: #f1e5c6;
      border: tall #3a3222; padding: 0 2;
    }
    Input:focus { border: tall #d9b45c; }

    ListView { background: #15120c; border: tall #3a3222; padding: 1; }
    ListItem { padding: 0 2; }
    ListItem:hover { background: #241f15; color: #e8c266; }
    ListItem.--highlighted { background: #312a1a; color: #f2d78a; }

    ProgressBar { height: 1; margin: 1 0; }
    ProgressBar > .bar { color: #d9b45c; background: #221d13; }
    .bar--complete { color: #e8c266; }

    Header { background: #1a1711; color: #d9c58a; }
    Header .header-title { color: #f0d27e; text-style: bold; }
    Footer { background: #1a1711; color: #b7a984; }
    Footer .footer-key { color: #e8c266; }
    """

    SCREENS = {
        "welcome": WelcomeScreen,
        "token": TokenScreen,
        "account": AccountScreen,
        "worker": WorkerScreen,
        "deploy": DeployScreen,
        "config": ConfigScreen,
        "cleanip": CleanIPScreen,
        "done": DoneScreen,
    }

    BINDINGS = [Binding("ctrl+q", "quit", "Quit")]

    def on_mount(self):
        self.push_screen("welcome")


def main():
    set_lang(sys.argv[1] if len(sys.argv) > 1 else "auto")
    CfConsoleApp().run()


if __name__ == "__main__":
    main()
