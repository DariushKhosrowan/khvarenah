"""Cloudflare Workers API client with human-friendly error classification.

Targets the Workers Scripts / Settings / Subdomain endpoints so the console can
deploy the edgetunnel VLESS worker and manage it without the Node/wrangler CLI.
Pure `requests` -> runs on Linux and Windows identically.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

API = "https://api.cloudflare.com/client/v4"
DEFAULT_COMPAT_DATE = "2026-07-01"


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

# CF API error codes we know how to explain.  code -> (title, fix)
KNOWN_CODES: dict[int, tuple[str, str]] = {
    10000: ("Authentication failure", "The API token was rejected. Re-enter it (or create a new one in the Cloudflare dashboard)."),
    9109: ("Invalid API token", "The token is malformed or empty. Paste a full token from Cloudflare → My Profile → API Tokens."),
    6003: ("Insufficient permission", "The token lacks a required permission. Recreate it with at least: Account-Settings-Read, Workers-Scripts-Edit, Workers-KV-Storage-Edit, Workers-Scripts-Read."),
    10021: ("Too many requests", "You hit a rate limit. Wait ~30s and retry."),
    10022: ("Not authenticated", "Token missing/expired. Re-authenticate."),
    9106: ("Script deleted", "This worker was deleted in the dashboard."),
    8000001: ("Worker script error", "The uploaded script failed to parse/validate. Check that the worker JS is the correct edgetunnel module file."),
}


@dataclass
class CFError(Exception):
    """A structured, human-readable error with a suggested fix."""

    title: str
    detail: str
    fix: str
    status: Optional[int] = None
    code: Optional[int] = None
    raw: dict = field(default_factory=dict)

    def __str__(self) -> str:  # friendly one-liner for TUI/CLI
        return f"{self.title}: {self.detail}"


def explain_response(resp: requests.Response, action: str) -> CFError:
    """Build a CFError from a non-2xx Cloudflare response.

    Falls back gracefully when the body isn't the standard CF envelope.
    """
    status = resp.status_code
    try:
        body = resp.json()
    except Exception:
        body = {}
    raw = body if isinstance(body, dict) else {"_": body}

    # Pull an error code / message out of the CF envelope.
    code = None
    detail = ""
    errs = raw.get("errors") or []
    if errs and isinstance(errs, list):
        e0 = errs[0]
        code = e0.get("code") if isinstance(e0, dict) else None
        detail = e0.get("message", "") if isinstance(e0, dict) else str(e0)
    if not detail:
        detail = raw.get("errors") or raw.get("messages") or resp.text[:220]

    title, fix = "Request failed", ""
    if code in KNOWN_CODES:
        title, fix = KNOWN_CODES[code]
    elif status == 400:
        title, fix = "Bad request", "One of the fields is invalid. Verify the worker name (lowercase letters, numbers, hyphens) and re-check the script."
    elif status == 401:
        title, fix = "Not authenticated", "The API token is invalid or expired. Get a fresh token from Cloudflare → My Profile → API Tokens."
    elif status == 403:
        title, fix = "Permission denied", "The token is missing a required permission. Recreate it with Workers-Scripts-Edit & Account-Settings-Read (see the 'Create Token' guidance in the console)."
    elif status == 404:
        title, fix = "Not found", "Check the Account ID and that the worker name is correct. The account may not be accessible with this token."
    elif status == 409:
        title, fix = "Conflict", "A resource with this name already exists in a conflicting state. Pick another worker name or delete the existing one."
    elif status == 413:
        title, fix = "Script too large", "The worker bundle is over the size limit. Use the standard edgetunnel worker file."
    elif status == 429:
        title, fix = "Rate limited", "Slow down — wait a few seconds and retry. Free-tier limits apply."
    elif status >= 500:
        title, fix = "Cloudflare-side error", "This is a Cloudflare outage/5xx. Wait briefly and retry."
    else:
        fix = "Review the raw error below and adjust accordingly."

    return CFError(title=title, detail=detail or resp.text[:220], fix=fix,
                   status=status, code=code, raw=raw)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class Config:
    """Client wrapper. All network calls are plain blocking requests (slow but
    portable); the TUI runs them on a worker thread so the UI stays live."""

    def __init__(self, token: str, timeout: int = 25):
        self.token = token.strip()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })

    # -- helpers ------------------------------------------------------------

    def _request(self, method: str, path: str,
                 *, json_body: Any = None, files: Optional[dict] = None,
                 headers: Optional[dict] = None, action: str = "",
                 timeout: Optional[int] = None) -> dict:
        url = f"{API}{path}"
        eff_to = timeout or self.timeout
        try:
            resp = self.session.request(method, url, json=json_body, files=files,
                                        headers=headers, timeout=eff_to)
        except requests.exceptions.SSLError:
            raise CFError("TLS error", "Could not establish a secure connection to Cloudflare.",
                          "Check your network / proxy settings.")
        except requests.exceptions.ConnectionError:
            raise CFError("Network error", f"Could not reach {API}.",
                          "Are you offline? Cloudflare may be blocked/filtered where you are — "
                          "the console still works for generating configs and local testing.")
        except requests.exceptions.Timeout:
            raise CFError("Timeout", f"No response from Cloudflare after {eff_to}s.",
                          "Retry; if it persists, the API may be blocked on your network.")
        except Exception as e:  # noqa: BLE001
            raise CFError("Unexpected error", str(e), "Review the error and try again.")

        if resp.status_code >= 200 and resp.status_code < 300:
            try:
                return resp.json() if resp.content else {}
            except Exception:
                return {}
        raise explain_response(resp, action or f"{method} {path}")

    # -- auth / account ------------------------------------------------------

    def verify_token(self) -> dict:
        return self._request("GET", "/user/tokens/verify", action="verify token")

    def list_accounts(self) -> list[dict]:
        data = self._request("GET", "/accounts?per_page=100", action="list accounts")
        return data.get("result", [])

    def get_subdomain(self, account_id: str) -> str:
        data = self._request("GET", f"/accounts/{account_id}/workers/subdomain",
                             action="get workers subdomain")
        return data.get("result", {}).get("subdomain", "")

    # -- scripts ---------------------------------------------------------------

    def list_scripts(self, account_id: str) -> list[dict]:
        data = self._request("GET", f"/accounts/{account_id}/workers/scripts?per_page=50",
                             action="list scripts")
        return data.get("result", [])

    def deploy_script(self, account_id: str, name: str, js: bytes,
                      *, compat_date: str = DEFAULT_COMPAT_DATE,
                      timeout: int = 120, retries: int = 2) -> dict:
        """Upload a module worker (with a couple of retries on 429/5xx)."""
        last: Optional[CFError] = None
        for attempt in range(retries + 1):
            try:
                return self._deploy_once(account_id, name, js, compat_date, timeout)
            except CFError as e:
                last = e
                if e.status is not None and e.status not in (429,) and not (e.status or 0) >= 500:
                    raise
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))
        assert last is not None
        raise last

    def _deploy_once(self, account_id: str, name: str, js: bytes,
                     compat_date: str, timeout: int) -> dict:
        metadata = json.dumps({
            "main_module": "_worker.js",
            "compatibility_date": compat_date,
            "compatibility_flags": ["nodejs_compat"],
        })
        files = {
            "metadata": (None, metadata, "application/json"),
            "_worker.js": ("_worker.js", js, "application/javascript"),
        }
        return self._request("PUT", f"/accounts/{account_id}/workers/scripts/{name}",
                             files=files, action="deploy worker", timeout=timeout)

    def set_vars(self, account_id: str, name: str, vars_dict: dict) -> dict:
        return self._request("PATCH", f"/accounts/{account_id}/workers/scripts/{name}/settings",
                             json_body={"vars": vars_dict}, action="set worker vars")

    def delete_script(self, account_id: str, name: str) -> dict:
        return self._request("DELETE", f"/accounts/{account_id}/workers/scripts/{name}",
                             action="delete worker")

    # -- derived helpers ----------------------------------------------------------

    def account_display(self, account: dict) -> str:
        return f"{account.get('name', '')} ({account.get('id', '')})"

    def workers_dev_url(self, account_id: str, name: str) -> str:
        return f"https://{name}.{self.get_subdomain(account_id)}.workers.dev"

    @staticmethod
    def public_hostname_from_url(url: str) -> str:
        return url.replace("https://", "").split("/")[0]
