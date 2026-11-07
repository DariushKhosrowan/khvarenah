"""Khvarenah — modern desktop GUI (PySide6/Qt6).

A polished, native-feeling desktop app for creating and controlling a
Cloudflare-Worker VLESS proxy.  It reuses every core module from the console
(cf_api, worker_bundle, vless, deploy_wrangler, cleanip, i18n) behind a
real windowed UI:

    Welcome → Token → Account → Worker → Deploy → Config → Done
    + a "Find clean IPs" (SenPaiScanner) utility page.

Design: dark "royal gold" theme (the Khosrowan brand), a left stepper rail,
a slim top header with the current step breadcrumb + autopilot badge, a
content stack on the right, background worker threads for every network /
subprocess call so the UI never freezes.

Run:  python -m khvarenah.gui   (or: khvarenah — GUI is now the default)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QPushButton, QProgressBar,
    QScrollArea, QSizePolicy, QStackedWidget, QTextEdit, QVBoxLayout,
    QWidget,
)

# Core logic — reused unchanged from the console.
from khvarenah.i18n import tr, set_lang
from khvarenah.cf_api import Config, CFError
from khvarenah.worker_bundle import (
    find_worker_js, safe_worker_name, generate_uuid, validate_worker_js,
    default_worker_name, worker_name_from_account,
)
from khvarenah.vless import VlessProfile
from khvarenah.deploy_wrangler import (
    deploy_wrangler, create_token_instructions, WranglerMissingError,
)
from khvarenah.cleanip import find_clean_ips, rewrite_vless_with_endpoint
from khvarenah.updater import (
    load_config, save_config, check_and_apply,
)
from khvarenah import store

try:  # package version, if present
    from khvarenah import __version__ as VERSION
except Exception:  # pragma: no cover
    VERSION = ""

ASSETS = Path(__file__).resolve().parent / "assets"

STEPS = [
    ("welcome", "welcome.title"),
    ("token", "token.title"),
    ("account", "account.title"),
    ("worker", "worker.title"),
    ("deploy", "deploy.title"),
    ("config", "config.title"),
    ("done", "done.title"),
]

_ORDER = [k for k, _ in STEPS]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repolish(w: QWidget) -> None:
    """Force a stylesheet re-apply so object-name changes take effect."""
    w.style().unpolish(w)
    w.style().polish(w)


def _card() -> QFrame:
    """A rounded surface card (styled globally via QSS)."""
    f = QFrame()
    f.setObjectName("card")
    f.setProperty("class", "card")
    return f


def _margins(lo, m=26):
    lo.setContentsMargins(m, m, m, m)
    lo.setSpacing(12)
    return lo


def _hint(text: str, page: QWidget) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setObjectName("body")
    return lbl


def _icon() -> QIcon:
    return QIcon(str(ASSETS / "golden.png"))


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

QSS = """
* { outline: none; }

QMainWindow, QWidget#root { background: #0f0d09; }

/* ---- sidebar stepper ---- */
QFrame#sidebar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #1c1812, stop:1 #131009);
    border-right: 1px solid #2e281b;
}

QLabel#brand {
    color: #f0d27e; font-size: 20px; font-weight: 800;
    letter-spacing: 0.5px; padding: 6px 2px 0 2px;
}
QLabel#brand_sub {
    color: #8a7c5c; font-size: 11px; font-weight: 500;
    padding: 0 2px 10px 2px;
}

QLabel#stepcount {
    color: #8a7c5c; font-size: 10px; font-weight: 700;
    letter-spacing: 3px; padding: 2px 2px 6px 2px;
}

QPushButton#step {
    text-align: left; padding: 9px 12px;
    border: none; border-radius: 9px;
    color: #b7a984; font-size: 13px; font-weight: 500;
    background: transparent;
}
QPushButton#step:hover { background: #241f15; color: #e8c266; }
QPushButton#step:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #362d1c, stop:1 #2e271a);
    color: #f6df9d;
    border-left: 3px solid #d9b45c;
}
QPushButton#step:checked:hover { background: #3a3220; }
QPushButton#step:disabled { color: #4a4433; }

QLabel#step_num {
    color: #7a6c50; font-size: 11px; font-weight: 800;
    min-width: 18px;
}
QPushButton#step:checked QLabel#step_num { color: #f0d27e; }

QPushButton#step QLabel#step_text {
    color: #b7a984; font-size: 13px; font-weight: 500;
    background: transparent; border: none;
}
QPushButton#step:hover QLabel#step_text { color: #e8c266; }
QPushButton#step:checked QLabel#step_text { color: #f6df9d; }

/* utility link at the bottom of the sidebar */
QPushButton#step.util QLabel#step_text { color: #9a8a64; font-size: 12px; }

/* ---- top header ---- */
QFrame#header {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #17140f, stop:1 #0f0d09);
    border-bottom: 1px solid #2e281b;
    border-radius: 0px;
}
QLabel#step_chip {
    color: #cbb87e; font-size: 12px; font-weight: 600;
    background: #1a1610; border: 1px solid #2e281b;
    border-radius: 14px; padding: 4px 12px;
}
QLabel#ap_chip {
    color: #0f0d09; font-size: 11px; font-weight: 800;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #f0d27e, stop:1 #d9b45c);
    border-radius: 12px; padding: 4px 12px;
}
QLabel#ver_chip {
    color: #6a5d41; font-size: 11px; font-weight: 500;
    padding: 2px 4px;
}

/* ---- content ---- */
QWidget#content { background: #0f0d09; }
QFrame#card, QFrame.card {
    background: #181510;
    border: 1px solid #2d2719;
    border-top: 1px solid #382f1e;
    border-radius: 16px;
}
QFrame#mini {
    background: #1a1711;
    border: 1px solid #2d2719;
    border-top: 1px solid #3a3120;
    border-radius: 12px;
}

QLabel#page_title { color: #f1e5c6; font-size: 23px; font-weight: 800; }
QLabel#page_sub { color: #8a7c5c; font-size: 12px; }
QLabel#h { color: #d9c58a; font-size: 12px; font-weight: 700;
            letter-spacing: 0.3px; }
QLabel#body { color: #b7a984; font-size: 13px; line-height: 1.35; }

/* ---- checkboxes ---- */
QCheckBox {
    color: #b7a984; font-size: 13px; spacing: 9px; background: transparent;
}
QCheckBox:hover { color: #e8c266; }
QCheckBox::indicator {
    width: 17px; height: 17px;
    border: 1px solid #3a3222; border-radius: 5px;
    background: #17140e;
}
QCheckBox::indicator:hover { border-color: #6b5a2e; }
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #e8c266, stop:1 #cdab4e);
    border-color: #e8c266;
}

/* ---- inputs ---- */
QLineEdit {
    background: #15120c; border: 1px solid #3a3222; border-radius: 9px;
    padding: 10px 12px; color: #f1e5c6; font-size: 13px;
    selection-background-color: #d9b45c; selection-color: #1a1711;
}
QLineEdit:hover { border-color: #554827; }
QLineEdit:focus { border: 1px solid #d9b45c; }
QLineEdit::placeholder { color: #5c5340; }
QLineEdit[password="true"] { color: #e8c266; letter-spacing: 1px; }

QTextEdit {
    background: #15120c; border: 1px solid #3a3222; border-radius: 9px;
    color: #c9b784; font-size: 12px; padding: 8px;
    selection-background-color: #d9b45c; selection-color: #1a1711;
}
QTextEdit:focus { border-color: #d9b45c; }

QListWidget {
    background: #15120c; border: 1px solid #3a3222; border-radius: 9px;
    outline: none; padding: 5px; color: #b7a984;
    selection-background-color: transparent;
}
QListWidget::item { padding: 9px 11px; border-radius: 7px; margin-bottom: 2px; }
QListWidget::item:hover { background: #241f15; }
QListWidget::item:selected { background: #312a1a; color: #f2d78a; }

/* ---- buttons ---- */
QPushButton {
    background: #2a2317; border: 1px solid #3a3222;
    border-radius: 10px; padding: 9px 16px;
    color: #d9c58a; font-size: 13px; font-weight: 600;
}
QPushButton:hover { background: #362d1d; border-color: #6b5a2e; }
QPushButton:pressed { background: #241f15; }
QPushButton:disabled { color: #4a4433; background: #1a1711; border-color: #2d2719; }
QPushButton:focus-visible { border: 2px solid #f0d27e; }

QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #e8c266, stop:1 #cdab4e);
    color: #17130b; border: none; border-radius: 10px;
}
QPushButton#primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #f3d680, stop:1 #d9b45c);
}
QPushButton#primary:pressed { background: #c3a146; }
QPushButton#primary:disabled { background: #3a3220; color: #6a5d41; }

QPushButton#ghost { background: transparent; border: 1px solid #3a3222; }
QPushButton#ghost:hover { background: #1d1912; border-color: #6b5a2e; }

QPushButton#danger { color: #e0a49a; border-color: #5a3028; }
QPushButton#danger:hover { background: #2a1713; border-color: #8a463a; }

QPushButton#copy { background: #2a2317; border: 1px solid #554827; }
QPushButton#copy:hover { background: #362d1d; border-color: #8a773f; }

QPushButton#ok { color: #0f0d09; background: #7fbf8a; border: none; }

/* ---- progress ---- */
QProgressBar {
    border: none; border-radius: 7px; background: #221d13;
    height: 11px; text-align: center; color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #b8933f, stop:1 #f0d27e);
    border-radius: 7px;
}

/* ---- scrollbars ---- */
QScrollBar:vertical {
    background: transparent; width: 11px; margin: 2px;
}
QScrollBar::handle:vertical {
    background: #3a3222; border-radius: 5px; min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: #554827; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QScrollBar:horizontal {
    background: transparent; height: 11px; margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #3a3222; border-radius: 5px; min-width: 28px;
}
QScrollBar::handle:horizontal:hover { background: #554827; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

QScrollArea { border: none; background: transparent; }
QWidget#scrollbody { background: transparent; }

/* ---- status / text ---- */
QLabel#ok { color: #7fbf8a; font-size: 13px; }
QLabel#err {
    color: #e0a49a; font-size: 13px;
    background: #22140f; border: 1px solid #5a3028;
    border-radius: 9px; padding: 8px 11px;
}
QLabel#mono {
    background: #15120c; border: 1px solid #2d2719;
    border-radius: 9px; padding: 11px;
    color: #e8c266; font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace;
    font-size: 12px;
}

QFrame#sep { background: #2d2719; max-height: 1px; min-height: 1px; }
QLabel#footer { color: #5c5340; font-size: 11px; }

/* ---- menus / dialogs / tooltips ---- */
QMenu {
    background: #1a1711; border: 1px solid #3a3222; border-radius: 8px;
    padding: 5px; color: #d9c58a;
}
QMenu::item { padding: 6px 20px; border-radius: 6px; }
QMenu::item:selected { background: #312a1a; color: #f2d78a; }

QDialog { background: #12100d; }
QMessageBox { background: #12100d; }
QMessageBox QLabel { color: #d9c58a; font-size: 13px; }
QMessageBox QPushButton { min-width: 76px; }

QToolTip {
    background: #221d13; color: #f0e4c8;
    border: 1px solid #3a3222; border-radius: 6px;
    padding: 4px 8px; font-size: 12px;
}
"""

# ---------------------------------------------------------------------------
# Background task thread
# ---------------------------------------------------------------------------

class TaskThread(QThread):
    """Run a blocking callable off the UI thread, deliver one result/error."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._keep = self  # prevent GC mid-run

    def run(self) -> None:
        try:
            self.succeeded.emit(self._fn())
        except WranglerMissingError as e:
            self.failed.emit(f"\u2717 {e}")
        except CFError as e:
            self.failed.emit(f"\u2717 {e.title} \u2014 {e.detail}\nFix: {e.fix}")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"\u2717 {e}")


# ---------------------------------------------------------------------------
# Shared app state (mirrors the TUI's State)
# ---------------------------------------------------------------------------

class State:
    token = ""
    accounts: list = []
    account_id = ""
    name = ""
    uuid = ""
    worker_path: Path | None = None
    host = ""
    prof: VlessProfile | None = None
    autopilot = False
    subdomain = ""
    auto_update = load_config().get("auto_update", True)


STATE = State()


def _restore_prof(state=None) -> bool:
    """Restore the last saved deployment into ``state.prof``.

    Khvarenah persists every generated vless config to ``~/.khvarenah`` but
    never re-hydrated it on a fresh launch — leaving ``prof`` None so the
    Clean-IP page wrongly claimed "No deployed config available" even when a
    worker was already deployed and saved.  This restores the most recent
    saved deployment so the scanner works across restarts and in autopilot.
    """
    st = state or STATE
    if st.prof is not None:
        return True
    rec = store.last_vless()
    if not rec or not rec.get("address"):
        return False
    st.prof = VlessProfile(
        uuid=rec.get("uuid", "") or "",
        address=rec["address"],
        port=int(rec.get("port") or 443),
        name=rec.get("name") or "cf-worker-edge",
    )
    if not st.uuid:
        st.uuid = getattr(st.prof, "uuid", "")
    if not st.host:
        st.host = st.prof.address
    if not st.name:
        st.name = st.prof.name
    return True

# ---------------------------------------------------------------------------
# Sidebar stepper
# ---------------------------------------------------------------------------

class StepButton(QPushButton):
    def __init__(self, text: str, index, parent=None, util: bool = False):
        super().__init__(parent)
        self.setObjectName("step" + (" util" if util else ""))
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 8, 0)
        row.setSpacing(10)
        num = QLabel(str(index) if index != "⛁" else "⛁")
        num.setObjectName("step_num")
        label = QLabel(text)
        label.setObjectName("step_text")
        row.addWidget(num)
        row.addWidget(label, 1)
        self._num = num
        self._idx = index

    def set_done(self, done: bool) -> None:
        if done and self._idx != "⛁":
            self._num.setText("\u2713")
        elif not done and self._idx != "⛁":
            self._num.setText(str(self._idx))


# ---------------------------------------------------------------------------
# Top header bar
# ---------------------------------------------------------------------------

class HeaderBar(QFrame):
    """Slim top bar: current-step breadcrumb on the left, autopilot badge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("header")
        self.setFixedHeight(52)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(20, 0, 20, 0)
        lo.setSpacing(10)

        self.step_chip = QLabel("")
        self.step_chip.setObjectName("step_chip")
        lo.addWidget(self.step_chip)

        self.ap_chip = QLabel("\u26a1 Autopilot ON")
        self.ap_chip.setObjectName("ap_chip")
        self.ap_chip.setVisible(False)
        lo.addWidget(self.ap_chip)

        lo.addStretch(1)

        self.ver_chip = QLabel(f"v{VERSION}" if VERSION else "")
        self.ver_chip.setObjectName("ver_chip")
        lo.addWidget(self.ver_chip)

    def set_step(self, text: str) -> None:
        self.step_chip.setText(text)

    def set_ap(self, on: bool) -> None:
        self.ap_chip.setVisible(on)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

class WelcomePage(QWidget):
    def __init__(self, win: "KhvarenahWindow", parent=None):
        super().__init__(parent)
        self.win = win
        lo = QVBoxLayout(self)
        _margins(lo)

        card = _card()
        clo = QVBoxLayout(card)
        _margins(clo, 24)

        emblem = QLabel()
        pix = QPixmap(str(ASSETS / "golden.png"))
        if not pix.isNull():
            emblem.setPixmap(pix.scaledToHeight(104, Qt.SmoothTransformation))
        emblem.setAlignment(Qt.AlignCenter)
        clo.addWidget(emblem)

        title = QLabel(tr("welcome.title"))
        title.setObjectName("page_title")
        title.setAlignment(Qt.AlignCenter)
        clo.addWidget(title)

        sub = QLabel("Cloudflare-Worker VLESS proxy \u00b7 0 \u2192 100")
        sub.setObjectName("page_sub")
        sub.setAlignment(Qt.AlignCenter)
        clo.addWidget(sub)

        body = _hint(
            "The ancient Persian royal glory. Create and control a "
            "Cloudflare-Worker VLESS proxy in a few steps \u2014 token, "
            "account, worker, deploy, and a ready-to-copy vless link.",
            self,
        )
        body.setAlignment(Qt.AlignCenter)
        clo.addWidget(body)

        # mini step cards
        cards = QHBoxLayout()
        cards.setSpacing(12)
        for i, (key, label) in enumerate(STEPS[1:], start=1):
            c = QFrame()
            c.setObjectName("mini")
            c.setProperty("class", "mini")
            v = QVBoxLayout(c)
            v.setContentsMargins(14, 10, 14, 10)
            v.setSpacing(6)
            n = QLabel(str(i))
            n.setStyleSheet("color:#f0d27e;font-weight:800;font-size:15px;")
            t = QLabel(tr(label))
            t.setWordWrap(True)
            t.setStyleSheet("color:#b7a984;font-size:12px;")
            v.addWidget(n)
            v.addWidget(t)
            cards.addWidget(c)
        clo.addLayout(cards)

        btnrow = QHBoxLayout()
        btnrow.setSpacing(10)
        start = QPushButton(tr("welcome.start"))
        start.setObjectName("primary")
        start.setCursor(Qt.PointingHandCursor)
        start.setToolTip("Begin the 0 \u2192 100 wizard")
        start.clicked.connect(lambda: self.win.goto("token"))
        ao = QPushButton(tr("welcome.autopilot"))
        ao.setCursor(Qt.PointingHandCursor)
        ao.setToolTip("Paste your token once \u2014 Khvarenah does the rest")
        ao.clicked.connect(self._autopilot)
        btnrow.addStretch(1)
        btnrow.addWidget(ao)
        btnrow.addWidget(start)
        btnrow.addStretch(1)
        clo.addLayout(btnrow)

        # auto-update row
        updrow = QHBoxLayout()
        updrow.setSpacing(8)
        self.auto_upd = QCheckBox("\u2713 Auto-update from GitHub")
        self.auto_upd.setChecked(STATE.auto_update)
        self.auto_upd.toggled.connect(self._toggle_auto_update)
        updrow.addWidget(self.auto_upd)
        updrow.addStretch(1)
        self.upd_status = QLabel("")
        self.upd_status.setObjectName("body")
        updrow.addWidget(self.upd_status)
        clo.addLayout(updrow)

        # memory summary
        self.mem = QLabel(store.memory_summary())
        self.mem.setObjectName("body")
        self.mem.setWordWrap(True)
        self.mem.setAlignment(Qt.AlignCenter)
        clo.addWidget(self.mem)

        lo.addWidget(card)
        lo.addStretch(1)

    def _toggle_auto_update(self, on: bool):
        STATE.auto_update = bool(on)
        save_config({"auto_update": STATE.auto_update})

    def _autopilot(self):
        STATE.autopilot = True
        self.win.goto("token")


class TokenPage(QWidget):
    def __init__(self, win: "KhvarenahWindow", parent=None):
        super().__init__(parent)
        self.win = win
        lo = QVBoxLayout(self)
        _margins(lo)

        card = _card()
        clo = QVBoxLayout(card)
        _margins(clo, 22)

        title = QLabel(tr("token.title"))
        title.setObjectName("page_title")
        clo.addWidget(title)

        self._instr = QTextEdit()
        self._instr.setReadOnly(True)
        self._instr.setPlainText(create_token_instructions())
        self._instr.setMaximumHeight(96)
        clo.addWidget(self._instr)

        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText(tr("token.placeholder"))
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setProperty("password", True)
        self.token_edit.returnPressed.connect(self._verify)
        self.token_edit.textChanged.connect(lambda _: self._set_err(""))
        clo.addWidget(self.token_edit)

        btnrow = QHBoxLayout()
        self.verify_btn = QPushButton(tr("token.verify"))
        self.verify_btn.setObjectName("primary")
        self.verify_btn.setCursor(Qt.PointingHandCursor)
        self.verify_btn.clicked.connect(self._verify)
        btnrow.addWidget(self.verify_btn)
        btnrow.addStretch(1)
        clo.addLayout(btnrow)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        clo.addWidget(self.status)

        lo.addWidget(card)
        lo.addStretch(1)

    def _set_err(self, msg: str):
        if msg:
            self.status.setObjectName("err")
        else:
            self.status.setObjectName("ok")
        self.status.setText(msg)
        _repolish(self.status)

    def _verify(self):
        tok = self.token_edit.text().strip()
        if not tok:
            self._set_err(tr("token.empty").replace("[red]", "").replace("[/]", ""))
            return
        STATE.token = tok
        store.save_token(tok)
        self._set_err("")

        self.verify_btn.setEnabled(False)
        self.status.setObjectName("ok")
        self.status.setText("verifying\u2026")

        def work():
            c = Config(tok, timeout=30)
            c.verify_token()
            accounts = c.list_accounts()
            subdomain = ""
            if accounts:
                try:
                    subdomain = c.get_subdomain(accounts[0]["id"])
                except Exception:  # noqa: BLE001
                    subdomain = ""
            return accounts, subdomain

        def ok(res):
            accounts, subdomain = res
            self.verify_btn.setEnabled(True)
            if not accounts:
                self._set_err(
                    tr("token.none").replace("[red]", "").replace("[/]", "")
                    .replace("[yellow]", "").replace("[/]", ""))
                return
            STATE.accounts = accounts
            STATE.subdomain = subdomain
            self.status.setObjectName("ok")
            self.status.setText(f"\u2713 verified \u2014 {len(accounts)} account(s)")
            _repolish(self.status)
            self.win.goto("account")

        def fail(msg):
            self.verify_btn.setEnabled(True)
            self._set_err(msg)

        self._thread = TaskThread(work, self)
        self._thread.succeeded.connect(ok)
        self._thread.failed.connect(fail)
        self._thread.start()


class AccountPage(QWidget):
    def __init__(self, win: "KhvarenahWindow", parent=None):
        super().__init__(parent)
        self.win = win
        lo = QVBoxLayout(self)
        _margins(lo)

        card = _card()
        clo = QVBoxLayout(card)
        _margins(clo, 22)

        title = QLabel(tr("account.title"))
        title.setObjectName("page_title")
        clo.addWidget(title)
        clo.addWidget(_hint(
            "Choose the Cloudflare account your worker should live under.", self))

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._selected)
        clo.addWidget(self.list)

        btnrow = QHBoxLayout()
        back = QPushButton(tr("back"))
        back.setObjectName("ghost")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self.win.goto("token"))
        self.next_btn = QPushButton(tr("account.continue"))
        self.next_btn.setObjectName("primary")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(lambda: self.win.goto("worker"))
        btnrow.addWidget(back)
        btnrow.addStretch(1)
        btnrow.addWidget(self.next_btn)
        clo.addLayout(btnrow)

        lo.addWidget(card)
        lo.addStretch(1)

    def on_enter(self):
        self.list.clear()
        for acc in STATE.accounts:
            item = QListWidgetItem(Config.account_display(Config, acc))
            self.list.addItem(item)
        if STATE.accounts:
            self.list.setCurrentRow(0)
            STATE.account_id = STATE.accounts[0]["id"]
            self.next_btn.setEnabled(True)
            if STATE.autopilot:
                if not STATE.name and STATE.accounts:
                    STATE.name = worker_name_from_account(STATE.accounts[0])
                self.win.goto("worker")

    def _selected(self, row: int):
        if row >= 0 and row < len(STATE.accounts):
            STATE.account_id = STATE.accounts[row]["id"]
            self.next_btn.setEnabled(True)


class WorkerPage(QWidget):
    def __init__(self, win: "KhvarenahWindow", parent=None):
        super().__init__(parent)
        self.win = win
        lo = QVBoxLayout(self)
        _margins(lo)

        card = _card()
        clo = QVBoxLayout(card)
        _margins(clo, 22)

        title = QLabel(tr("worker.title"))
        title.setObjectName("page_title")
        clo.addWidget(title)
        clo.addWidget(_hint(
            "Name the worker (lowercase letters, digits, hyphens). A fresh "
            "UUID is generated automatically.", self))

        cls = QHBoxLayout()
        cls.setSpacing(12)
        namecol = QVBoxLayout()
        namecol.setSpacing(4)
        name_lbl = QLabel("Worker name")
        name_lbl.setObjectName("h")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("worker name (e.g. khosrowan)")
        self.name_edit.returnPressed.connect(self._continue)
        namecol.addWidget(name_lbl)
        namecol.addWidget(self.name_edit)
        uuidcol = QVBoxLayout()
        uuidcol.setSpacing(4)
        uuid_lbl = QLabel("UUID")
        uuid_lbl.setObjectName("h")
        self.uuid_edit = QLineEdit()
        self.uuid_edit.setPlaceholderText(tr("worker.uuid_ph"))
        uuidcol.addWidget(uuid_lbl)
        uuidcol.addWidget(self.uuid_edit)
        cls.addLayout(namecol, 1)
        cls.addLayout(uuidcol, 1)
        clo.addLayout(cls)

        self.bundle_lbl = QLabel("")
        self.bundle_lbl.setObjectName("body")
        self.bundle_lbl.setWordWrap(True)
        clo.addWidget(self.bundle_lbl)

        btnrow = QHBoxLayout()
        back = QPushButton(tr("back"))
        back.setObjectName("ghost")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self.win.goto("account"))
        self.next_btn = QPushButton(tr("worker.continue"))
        self.next_btn.setObjectName("primary")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(self._continue)
        btnrow.addWidget(back)
        btnrow.addStretch(1)
        btnrow.addWidget(self.next_btn)
        clo.addLayout(btnrow)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        clo.addWidget(self.msg)

        lo.addWidget(card)
        lo.addStretch(1)

    def on_enter(self):
        self.name_edit.setText(STATE.name or default_worker_name())
        if not STATE.uuid:
            STATE.uuid = generate_uuid()
        self.uuid_edit.setText(STATE.uuid)
        STATE.worker_path = find_worker_js()
        if STATE.worker_path:
            self.bundle_lbl.setText(f"worker bundle: {STATE.worker_path}")
            self.msg.setText("")
        else:
            self.bundle_lbl.setText(
                "worker bundle: not found \u2014 place _worker.js next to the console")
            self.msg.setObjectName("err")
            _repolish(self.msg)
            self.msg.setText(
                "No worker bundle found. Put the edgetunnel _worker.js beside "
                "the app before deploying.")
        if STATE.autopilot:
            self.name_edit.setText(default_worker_name())
            STATE.name = safe_worker_name(self.name_edit.text())
            STATE.uuid = self.uuid_edit.text().strip() or generate_uuid()
            self.uuid_edit.setText(STATE.uuid)
            self.win.goto("deploy")

    def _continue(self):
        STATE.name = safe_worker_name(self.name_edit.text())
        STATE.uuid = self.uuid_edit.text().strip() or generate_uuid()
        self.uuid_edit.setText(STATE.uuid)
        self.win.goto("deploy")


class DeployPage(QWidget):
    def __init__(self, win: "KhvarenahWindow", parent=None):
        super().__init__(parent)
        self.win = win
        lo = QVBoxLayout(self)
        _margins(lo)

        card = _card()
        clo = QVBoxLayout(card)
        _margins(clo, 22)

        title = QLabel(tr("deploy.title"))
        title.setObjectName("page_title")
        clo.addWidget(title)
        clo.addWidget(_hint(
            "Uploading the worker to Cloudflare and locking in your UUID.", self))

        self.pb = QProgressBar()
        self.pb.setRange(0, 0)          # indeterminate
        self.pb.setVisible(False)
        clo.addWidget(self.pb)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        clo.addWidget(self.status)

        self.copy_err_btn = QPushButton("\u29c9 Copy error")
        self.copy_err_btn.setObjectName("copy")
        self.copy_err_btn.setCursor(Qt.PointingHandCursor)
        self.copy_err_btn.setVisible(False)
        self.copy_err_btn.clicked.connect(self._copy_error)
        clo.addWidget(self.copy_err_btn)

        self._last_error = ""

        btnrow = QHBoxLayout()
        back = QPushButton(tr("back"))
        back.setObjectName("ghost")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self.win.goto("worker"))
        self.deploy_btn = QPushButton(tr("deploy.btn"))
        self.deploy_btn.setObjectName("primary")
        self.deploy_btn.setCursor(Qt.PointingHandCursor)
        self.deploy_btn.clicked.connect(self._deploy)
        btnrow.addWidget(back)
        btnrow.addStretch(1)
        btnrow.addWidget(self.deploy_btn)
        clo.addLayout(btnrow)

        lo.addWidget(card)
        lo.addStretch(1)

    def on_enter(self):
        if STATE.autopilot:
            self._deploy()

    def _deploy(self):
        wp = STATE.worker_path or find_worker_js()
        if not wp:
            self.status.setObjectName("err")
            _repolish(self.status)
            self.status.setText(
                "No worker bundle found. Place the edgetunnel _worker.js next "
                "to the app.")
            return
        ok, vmsg = validate_worker_js(wp)
        if not ok:
            self.status.setObjectName("err")
            _repolish(self.status)
            self.status.setText(vmsg)
            return

        self.deploy_btn.setEnabled(False)
        self.pb.setVisible(True)
        self.status.setObjectName("ok")
        self.status.setText(tr("deploy.starting"))

        def work():
            return deploy_wrangler(STATE.token, STATE.account_id, STATE.name,
                                   str(wp), STATE.uuid)

        def ok(res):
            self.pb.setVisible(False)
            self.deploy_btn.setEnabled(True)
            if not res.ok:
                self.status.setObjectName("err")
                _repolish(self.status)
                self._last_error = f"{res.message}\n{res.stderr or ''}".strip()
                self.status.setText(f"\u2717 {res.message}\n{res.stderr or ''}"[-600:])
                self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
                self.copy_err_btn.setVisible(True)
                return
            self.status.setTextInteractionFlags(Qt.NoTextInteraction)
            self.copy_err_btn.setVisible(False)
            STATE.host = res.host
            self.status.setText(f"\u2713 Deployed \u2014 host: {res.host}")
            store.remember_vless(
                VlessProfile(uuid=STATE.uuid, address=res.host, name=STATE.name))
            self.win.goto("cleanip" if STATE.autopilot else "config")

        def fail(msg):
            self.pb.setVisible(False)
            self.deploy_btn.setEnabled(True)
            self.status.setObjectName("err")
            _repolish(self.status)
            self.status.setText(msg)

        self._thread = TaskThread(work, self)
        self._thread.succeeded.connect(ok)
        self._thread.failed.connect(fail)
        self._thread.start()

    def _copy_error(self):
        if not self._last_error:
            return
        QApplication.clipboard().setText(self._last_error)
        self.copy_err_btn.setText("\u2713 error copied")
        self.copy_err_btn.setObjectName("ok")
        _repolish(self.copy_err_btn)

        def restore():
            self.copy_err_btn.setText("\u29c9 Copy error")
            self.copy_err_btn.setObjectName("copy")
            _repolish(self.copy_err_btn)

        QTimer.singleShot(1600, restore)


class ConfigPage(QWidget):
    def __init__(self, win: "KhvarenahWindow", parent=None):
        super().__init__(parent)
        self.win = win
        lo = QVBoxLayout(self)
        _margins(lo)

        card = _card()
        clo = QVBoxLayout(card)
        _margins(clo, 22)

        title = QLabel(tr("config.title"))
        title.setObjectName("page_title")
        clo.addWidget(title)
        clo.addWidget(_hint(
            "Your ready-to-use share link. Copy it into your vless client "
            "(v2rayN / NekoBox / \u2026).", self))

        self.link = QLabel("")
        self.link.setObjectName("mono")
        self.link.setWordWrap(True)
        self.link.setTextInteractionFlags(Qt.TextSelectableByMouse)
        clo.addWidget(self.link)

        btnrow = QHBoxLayout()
        back = QPushButton(tr("back"))
        back.setObjectName("ghost")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self.win.goto("deploy"))
        copy = QPushButton("\u29c9 " + tr("config.copy"))
        copy.setObjectName("copy")
        copy.setCursor(Qt.PointingHandCursor)
        copy.clicked.connect(self._copy)
        nxt = QPushButton("Done \u2192")
        nxt.setObjectName("primary")
        nxt.setCursor(Qt.PointingHandCursor)
        nxt.clicked.connect(lambda: self.win.goto("done"))
        btnrow.addWidget(back)
        btnrow.addStretch(1)
        btnrow.addWidget(copy)
        btnrow.addWidget(nxt)
        clo.addLayout(btnrow)

        self.copied = QLabel("")
        clo.addWidget(self.copied)

        lo.addWidget(card)
        lo.addStretch(1)

    def on_enter(self):
        if STATE.prof is None:
            STATE.prof = VlessProfile(uuid=STATE.uuid, address=STATE.host,
                                      name=STATE.name)
            store.remember_vless(STATE.prof)
        self.link.setText(STATE.prof.share_link())
        self.copied.setText("")
        if STATE.autopilot:
            self._copy()
            self.win.goto("done")

    def _copy(self):
        if STATE.prof is None:
            return
        QApplication.clipboard().setText(STATE.prof.share_link())
        self.copied.setObjectName("ok")
        _repolish(self.copied)
        self.copied.setText(
            tr("config.copied").replace("[green]", "").replace("[/]", ""))


class DonePage(QWidget):
    def __init__(self, win: "KhvarenahWindow", parent=None):
        super().__init__(parent)
        self.win = win
        lo = QVBoxLayout(self)
        _margins(lo)

        card = _card()
        clo = QVBoxLayout(card)
        _margins(clo, 22)

        title = QLabel("\u2713 " + tr("done.title"))
        title.setObjectName("page_title")
        clo.addWidget(title)

        self.summary = QLabel("")
        self.summary.setObjectName("body")
        self.summary.setWordWrap(True)
        clo.addWidget(self.summary)

        self.link = QLabel("")
        self.link.setObjectName("mono")
        self.link.setWordWrap(True)
        self.link.setTextInteractionFlags(Qt.TextSelectableByMouse)
        clo.addWidget(self.link)

        btnrow = QHBoxLayout()
        copy = QPushButton(tr("done.copy"))
        copy.setObjectName("copy")
        copy.setCursor(Qt.PointingHandCursor)
        copy.clicked.connect(self._copy)
        clean = QPushButton("Find clean IPs")
        clean.setCursor(Qt.PointingHandCursor)
        clean.clicked.connect(lambda: self.win.goto("cleanip"))
        quit_ = QPushButton(tr("quit"))
        quit_.setObjectName("ghost")
        quit_.setCursor(Qt.PointingHandCursor)
        quit_.clicked.connect(QApplication.instance().quit)
        btnrow.addWidget(quit_)
        btnrow.addStretch(1)
        btnrow.addWidget(clean)
        btnrow.addWidget(copy)
        clo.addLayout(btnrow)

        self.copied = QLabel("")
        clo.addWidget(self.copied)

        lo.addWidget(card)
        lo.addStretch(1)

    def on_enter(self):
        dash = "\u2014"
        link = STATE.prof.share_link() if STATE.prof else ""
        self.summary.setText(
            f"Host: {STATE.host}\nUUID: {STATE.uuid}\n"
            f"Subdomain: {STATE.subdomain or dash}")
        self.link.setText(link)
        self.copied.setText("")

    def _copy(self):
        if STATE.prof is None:
            return
        QApplication.clipboard().setText(STATE.prof.share_link())
        self.copied.setObjectName("ok")
        _repolish(self.copied)
        self.copied.setText("\u2713 copied")


class CleanIPPage(QWidget):
    def __init__(self, win: "KhvarenahWindow", parent=None):
        super().__init__(parent)
        self.win = win
        lo = QVBoxLayout(self)
        _margins(lo)

        card = _card()
        clo = QVBoxLayout(card)
        _margins(clo, 22)

        title = QLabel("Find clean Cloudflare IPs")
        title.setObjectName("page_title")
        clo.addWidget(title)
        clo.addWidget(_hint(
            "SenPaiScanner probes Cloudflare IPs against your deployed config "
            "and returns the fastest healthy endpoints.", self))

        self.pb = QProgressBar()
        self.pb.setRange(0, 0)
        self.pb.setVisible(False)
        clo.addWidget(self.pb)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        clo.addWidget(self.status)

        self.results = QListWidget()
        self.results.setVisible(False)
        self.results.itemDoubleClicked.connect(self._use_endpoint)
        clo.addWidget(self.results)

        self.hint = QLabel("")
        self.hint.setObjectName("body")
        self.hint.setVisible(False)
        clo.addWidget(self.hint)

        btnrow = QHBoxLayout()
        back = QPushButton("Back to Done")
        back.setObjectName("ghost")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self.win.goto("done"))
        self.scan_btn = QPushButton(tr("cleanip.btn"))
        self.scan_btn.setObjectName("primary")
        self.scan_btn.setCursor(Qt.PointingHandCursor)
        self.scan_btn.clicked.connect(self._scan)
        btnrow.addWidget(back)
        btnrow.addStretch(1)
        btnrow.addWidget(self.scan_btn)
        clo.addLayout(btnrow)

        lo.addWidget(card)
        lo.addStretch(1)

    def on_enter(self):
        _restore_prof(STATE)
        if STATE.prof is None:
            self.status.setObjectName("err")
            _repolish(self.status)
            self.status.setText(
                "No deployed config available \u2014 complete the wizard first.")
            self.scan_btn.setEnabled(False)
        else:
            self.status.setText("")
            self.scan_btn.setEnabled(True)
        self.results.setVisible(False)
        if STATE.autopilot and STATE.prof is not None and not getattr(self, "_scanned", False):
            self._scanned = True
            self._scan()

    def _use_endpoint(self, item):
        """Switch the active config to the double-clicked clean IP."""
        ep = item.text().strip()
        if not ep or ":" not in ep:
            return
        host, _, port = ep.rpartition(":")
        STATE.prof = VlessProfile(
            uuid=STATE.uuid, address=host,
            port=int(port) if port.isdigit() else 443,
            name=STATE.name + " (clean IP)",
        )
        store.remember_vless(STATE.prof, clean_ip=True)
        QApplication.clipboard().setText(STATE.prof.share_link())
        self.status.setText(f"\u2713 Using {ep} \u2014 link copied; continue to Config to copy again.")
        self.win.goto("config")

    def _scan(self):
        if STATE.prof is None:
            return
        link = STATE.prof.share_link()
        self.scan_btn.setEnabled(False)
        self.pb.setVisible(True)
        self.status.setObjectName("ok")
        self.status.setText("running SenPaiScanner\u2026 (this can take a while)")
        self.results.setVisible(False)

        def work():
            return find_clean_ips(link, count=800, workers=25, timeout_s=6,
                                  gentle=True, scan_timeout=360)

        def ok(res):
            self.pb.setVisible(False)
            self.scan_btn.setEnabled(True)
            if not res.ok:
                self.status.setObjectName("err")
                _repolish(self.status)
                self.status.setText(f"\u2717 {res.message}")
                if STATE.autopilot:
                    # fall back to the normal (workers.dev) config
                    self.win.goto("config")
                return
            self.status.setText(f"\u2713 {res.message}")
            self.results.clear()
            for ep in res.endpoints[:10]:
                item = QListWidgetItem(ep)
                self.results.addItem(item)
            self.results.setVisible(True)
            self.hint.setVisible(True)
            self.hint.setText(
                "Double-click any IP to switch to it \u2014 best IP is already "
                "copied to your clipboard and in memory.")
            if res.endpoints:
                host, _, port = res.endpoints[0].rpartition(":")
                STATE.prof = VlessProfile(
                    uuid=STATE.uuid, address=host,
                    port=int(port) if port.isdigit() else 443,
                    name=STATE.name + " (clean IP)",
                )
                store.remember_vless(STATE.prof, clean_ip=True)
                QApplication.clipboard().setText(STATE.prof.share_link())
                if STATE.autopilot:
                    self.win.goto("config")
                else:
                    Path("clean-configs.txt").write_text(
                        "\n\n".join(
                            f"# {ep}\n{rewrite_vless_with_endpoint(link, ep)}"
                            for ep in res.endpoints[:5]) + "\n")

        def fail(msg):
            self.pb.setVisible(False)
            self.scan_btn.setEnabled(True)
            self.status.setObjectName("err")
            _repolish(self.status)
            self.status.setText(msg)

        self._thread = TaskThread(work, self)
        self._thread.succeeded.connect(ok)
        self._thread.failed.connect(fail)
        self._thread.start()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class KhvarenahWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("app.title"))
        self.setWindowIcon(_icon())
        self.setMinimumSize(940, 640)
        self.resize(980, 700)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_lo = QHBoxLayout(root)
        root_lo.setContentsMargins(0, 0, 0, 0)
        root_lo.setSpacing(0)

        self._build_sidebar(root_lo)
        self._build_content(root_lo)

        self._pages = {
            "welcome": WelcomePage(self),
            "token": TokenPage(self),
            "account": AccountPage(self),
            "worker": WorkerPage(self),
            "deploy": DeployPage(self),
            "config": ConfigPage(self),
            "done": DonePage(self),
            "cleanip": CleanIPPage(self),
        }
        for key, page in self._pages.items():
            self.stack.addWidget(page)

        self._step_buttons = {}
        self._build_stepper()

        self.goto("welcome")

        if STATE.auto_update:
            self._start_self_update_check()

    # ---- self-update (background) ----

    def _start_self_update_check(self):
        """Check GitHub for a newer release; if found and auto-update is on,
        apply it in the background. A restart is required to use the new code."""

        def work():
            return check_and_apply()

        def ok(res):
            done, msg = res
            if done:
                page = self._pages.get("welcome")
                if hasattr(page, "upd_status"):
                    page.upd_status.setText(f"\U0001f501 {msg}")

        def fail(msg):
            page = self._pages.get("welcome")
            if hasattr(page, "upd_status"):
                page.upd_status.setText(f"\u26a0 update check: {msg}")

        self._upd_thread = TaskThread(work, self)
        self._upd_thread.succeeded.connect(ok)
        self._upd_thread.failed.connect(fail)
        self._upd_thread.start()

    # ---- UI construction ----

    def _build_sidebar(self, root_lo):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(236)
        s_lo = QVBoxLayout(sidebar)
        s_lo.setContentsMargins(14, 20, 14, 14)
        s_lo.setSpacing(2)

        brand = QLabel("\u2726 Khvarenah")
        brand.setObjectName("brand")
        s_lo.addWidget(brand)
        sub = QLabel("\u062e\u0648\u064e\u0631\u0646\u0647")
        sub.setObjectName("brand_sub")
        s_lo.addWidget(sub)

        count = QLabel("0 \u2192 100")
        count.setObjectName("stepcount")
        s_lo.addWidget(count)

        sep = QFrame()
        sep.setObjectName("sep")
        s_lo.addWidget(sep)

        self.stepper = QVBoxLayout()
        self.stepper.setSpacing(2)
        s_lo.addLayout(self.stepper)
        s_lo.addStretch(1)

        foot = QLabel("Cloudflare \u00b7 Worker VLESS")
        foot.setObjectName("footer")
        s_lo.addWidget(foot)

        root_lo.addWidget(sidebar)

    def _build_stepper(self):
        for i, (key, label) in enumerate(STEPS, start=1):
            b = StepButton(tr(label), i)
            b.clicked.connect(lambda _=False, k=key: self.goto(k))
            self.stepper.addWidget(b)
            self._step_buttons[key] = b
        sep = QFrame()
        sep.setObjectName("sep")
        sep.setMaximumHeight(1)
        self.stepper.addSpacing(8)
        self.stepper.addWidget(sep)
        self.stepper.addSpacing(8)
        util = StepButton("Find clean IPs", "⛁", util=True)
        util.clicked.connect(lambda: self.goto("cleanip"))
        self.stepper.addWidget(util)
        self._step_buttons["cleanip"] = util

    def _build_content(self, root_lo):
        content = QWidget()
        content.setObjectName("content")
        c_lo = QVBoxLayout(content)
        c_lo.setContentsMargins(0, 0, 0, 0)
        c_lo.setSpacing(0)

        self.header = HeaderBar()
        c_lo.addWidget(self.header)

        body = QWidget()
        body.setObjectName("content")
        b_lo = QVBoxLayout(body)
        b_lo.setContentsMargins(24, 22, 24, 22)
        self.stack = QStackedWidget()
        b_lo.addWidget(self.stack)
        c_lo.addWidget(body, 1)

        root_lo.addWidget(content, 1)

    # ---- navigation ----

    def _index(self, key: str) -> int:
        if key in _ORDER:
            return _ORDER.index(key)
        return 99  # utility page

    def _step_name(self, key: str) -> str:
        if key in dict(STEPS):
            return tr(dict(STEPS)[key])
        return "Find clean IPs"

    def goto(self, key: str):
        self.stack.setCurrentWidget(self._pages[key])
        page = self._pages[key]
        if hasattr(page, "on_enter"):
            page.on_enter()
        self._sync_stepper(key)
        # breadcrumb in the header
        if key in _ORDER:
            n = self._index(key) + 1
            self.header.set_step(f"Step {n} \u00b7 {len(_ORDER)} \u2014 {self._step_name(key)}")
        else:
            self.header.set_step(f"Utility \u2014 {self._step_name(key)}")
        self.header.set_ap(STATE.autopilot)

    def _sync_stepper(self, current: str):
        current_idx = self._index(current)
        for key, btn in self._step_buttons.items():
            idx = self._index(key)
            btn.setChecked(key == current)
            if key == "cleanip":
                continue
            btn.set_done(idx < current_idx)
            # completed or current steps are reachable; future steps are gated
            btn.setEnabled(idx <= current_idx + 1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    set_lang(sys.argv[1] if len(sys.argv) > 1 else "auto")
    app = QApplication(sys.argv)
    app.setApplicationName("Khvarenah")
    app.setWindowIcon(_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    try:
        font = QFont()
        font.setPointSize(10)
        app.setFont(font)
    except Exception:  # pragma: no cover
        pass
    win = KhvarenahWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
