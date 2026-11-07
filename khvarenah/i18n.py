"""Khvarenah i18n — lightweight English/Persian UI strings.

Keep it dependency-free: a dict of (key, (en, fa)) pairs plus a tiny
lookup. The default language follows the process locale; it can be
overridden by setting the KHVARENAH_LANG env var to "en" or "fa".

Note: Textual is not RTL-aware, so Persian is offered mainly for short
headings/labels; body help text stays bilingual in the docs.
"""

from __future__ import annotations

import locale
import os

_TR = {
    # ---- app / window ----
    "app.title": ("Cloudflare-Worker VPN Console", "کنسول VPN کلودفلر ورکر"),
    "app.subtitle": ("zero → 100", "صفر → ۱۰۰"),
    # ---- welcome ----
    "welcome.title": ("Khvarenah (خوَرنه)", "خوَرنه"),
    "welcome.body": (
        "**The ancient Persian royal glory.** A **0 → 100** wizard that creates "
        "and controls a Cloudflare-Worker VLESS proxy right from your terminal.\n\n"
        "**What you'll get**\n"
        "- a deployed `worker` reachable at `https://<name>.<subdomain>.workers.dev`\n"
        "- a ready-to-use `vless://…` config copied to your clipboard\n"
        "- friendly error explanations and fixes at every step\n\n"
        "**Steps**: {steps}\n\n"
        "> Press Enter to begin.",
        "**شکوه شاهانه باستانی.** یک **ویزارد صفر → ۱۰۰** که یک پروکسی VLESS ی "
        "کلودفلر ورکر را مستقیماً از ترمینال شما می‌سازد و کنترل می‌کند.",
    ),
    "welcome.start": ("Start", "شروع"),
    "welcome.autopilot": ("⚡ Autopilot", "⚡ خودکار"),
    "welcome.autopilot.body": (
        "**Autopilot** — paste your token once, then Khvarenah runs the whole "
        "wizard for you: picks an account, names the worker, deploys it, and "
        "shows your ready-to-copy vless link. No clicks needed.",
        "**حالت خودکار** — توکن را یک‌بار بچسبانید، سپس خوَرنه کل ویزارد را "
        "برای شما اجرا می‌کند.",
    ),
    "autopilot.label": ("Autopilot ON", "حالت خودکار روشن"),
    # ---- steps ----
    "step": ("Step {n}/{total} — {name}", "مرحله {n}/{total} — {name}"),
    # ---- token ----
    "token.title": ("Cloudflare API token", "توکن API کلودفلر"),
    "token.placeholder": ("paste API token", "توکن API را بچسبانید"),
    "token.verify": ("Verify & continue", "تأیید و ادامه"),
    "token.empty": ("[red]Token cannot be empty[/]", "[red]توکن نمی‌تواند خالی باشد[/]"),
    "token.working": ("verifying…", "در حال تأیید…"),
    "token.none": (
        "[red]No accounts are visible with this token.[/]\n"
        "[yellow]Fix: recreate the token and include Account-Settings:Read.[/]",
        "[red]با این توکن هیچ حسابی دیده نمی‌شود.[/]",
    ),
    # ---- account ----
    "account.title": ("pick account", "انتخاب حساب"),
    "account.continue": ("Continue", "ادامه"),
    # ---- worker ----
    "worker.title": ("worker name + UUID", "نام ورکر + UUID"),
    "worker.body": (
        "Give the worker a **name** (lowercase letters, digits, hyphens; max 64 chars). "
        "A fresh **UUID** is generated automatically — you can keep it or paste your own.",
        "به ورکر یک **نام** بدهید (حروف کوچک، رقم، خط تیره؛ حداکثر ۶۴ نویسه).",
    ),
    "worker.name_ph": ("worker name (e.g. my-vpn)", "نام ورکر (مثلاً my-vpn)"),
    "worker.uuid_ph": ("UUID (auto)", "UUID (خودکار)"),
    "worker.continue": ("Continue", "ادامه"),
    # ---- deploy ----
    "deploy.title": ("deploy", "استقرار"),
    "deploy.body": ("Uploading the worker and setting its UUID.", "در حال بارگذاری ورکر و تنظیم UUID آن."),
    "deploy.btn": ("Deploy now", "استقرار اکنون"),
    "deploy.starting": ("starting deploy…", "شروع استقرار…"),
    "deploy.done": ("[green]✔ Deployed. host: {host}[/]", "[green]✔ مستقر شد. میزبان: {host}[/]"),
    # ---- config ----
    "config.title": ("your vless config", "پیکربندی vless شما"),
    "config.body": ("Press **c** (or the button) to copy the share link.", "برای کپی لینک اشتراک، دکمه **c** را بزنید."),
    "config.copy": ("Copy to clipboard", "کپی در کلیپ‌بورد"),
    "config.copied": ("[green]✔ Copied to clipboard[/]", "[green]✔ در کلیپ‌بورد کپی شد[/]"),
    # ---- done ----
    "done.title": ("done", "انجام شد"),
    "done.copy": ("Copy vless link", "کپی لینک vless"),
    # ---- clean ip ----
    "cleanip.title": ("Find clean Cloudflare IPs (SenPaiScanner)", "یافتن IPهای تمیز کلودفلر"),
    "cleanip.btn": ("Start scan", "شروع اسکن"),
    # ---- common ----
    "back": ("Back", "بازگشت"),
    "quit": ("Quit", "خروج"),
    "copy": ("Copy config", "کپی پیکربندی"),
}

_VALUES = dict(_TR)


def _default_lang() -> str:
    env = os.environ.get("KHVARENAH_LANG")
    if env:
        return env.lower()[:2]
    try:
        return locale.getlocale(locale.LC_MESSAGES)[0][:2].lower()
    except Exception:  # noqa: BLE001
        return "en"


LANG = _default_lang()


def set_lang(lang: str) -> None:
    """Set language: 'en' or 'fa' (anything else falls back to English)."""
    global LANG
    LANG = lang.lower()[:2]
    if LANG not in ("en", "fa"):
        LANG = "en"


def tr(key: str, **kwargs) -> str:
    """Return the localized string for `key`, formatted with `kwargs`."""
    pair = _VALUES.get(key)
    if pair is None:
        return key
    text = pair[1] if LANG == "fa" else pair[0]
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
