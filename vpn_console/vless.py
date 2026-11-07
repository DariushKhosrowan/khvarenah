"""vless config + share-link generation for the edgetunnel worker.

Produces both the single-line `vless://...` share link (for v2rayN / v2rayNG /
NekoBox etc.) and a readable client config skeleton.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VlessProfile:
    uuid: str
    address: str          # hostname or IP (the worker's public host)
    port: int = 443
    security: str = "tls"
    path: str = "/"
    sni: Optional[str] = None         # defaults to address
    header_host: Optional[str] = None  # ws Host header, defaults to address
    transport: str = "ws"
    name: str = "cf-worker-edge"

    def __post_init__(self) -> None:
        if not self.sni:
            self.sni = self.address
        if not self.header_host:
            self.header_host = self.address

    # -- builder helpers ------------------------------------------------------

    def local_ws(self, lan_ip: str, port: int = 8787) -> "VlessProfile":
        """A copy pointing at a local wrangler-dev worker (VPN-free testing)."""
        return VlessProfile(
            uuid=self.uuid, address=lan_ip, port=port, security="none",
            path=self.path, sni=None, header_host=lan_ip, transport="ws",
            name="cf-worker-LOCAL (no VPN)",
        )

    # -- outputs ---------------------------------------------------------------

    def share_link(self) -> str:
        """The portable `vless://` URI used by client apps."""
        params = {
            "encryption": "none",
            "security": self.security,
            "type": self.transport,
            "sni": self.sni,
            "host": self.header_host,
            "path": self.path,
            "fp": "chrome",
        }
        display_name = urllib.parse.quote(self.name, safe="")
        return (f"vless://{self.uuid}@{self.address}:{self.port}"
                f"?{urllib.parse.urlencode(params)}#{display_name}")

    def xray_client_json(self) -> str:
        """A full xray client config (inbound socks/http + VLESS outbound)."""
        outbound = {
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": self.address,
                    "port": self.port,
                    "users": [{"id": self.uuid, "encryption": "none"}],
                }],
            },
            "streamSettings": {
                "network": self.transport,
                "security": self.security,
                "tlsSettings": {"serverName": self.sni, "fingerprint": "chrome"}
                if self.security == "tls" else None,
                "wsSettings": {
                    "path": self.path,
                    "headers": {"Host": self.header_host},
                },
            },
        }
        cfg = {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {"tag": "socks-in", "listen": "127.0.0.1", "port": 10808,
                 "protocol": "socks", "settings": {"auth": "noauth", "udp": True}},
                {"tag": "http-in", "listen": "127.0.0.1", "port": 10809,
                 "protocol": "http"},
            ],
            "outbounds": [outbound],
        }
        return json.dumps(cfg, indent=2)

    def v2ray_share_base64(self) -> str:
        """The share-link body already URL-encoded (kept for completeness)."""
        return self.share_link()
