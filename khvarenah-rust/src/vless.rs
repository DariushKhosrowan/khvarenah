//! vless config + share-link generation for the edgetunnel worker.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VlessProfile {
    pub uuid: String,
    /// hostname or IP (the worker's public host)
    pub address: String,
    #[serde(default = "default_port")]
    pub port: u16,
    #[serde(default = "default_security")]
    pub security: String,
    #[serde(default = "default_path")]
    pub path: String,
    /// defaults to address
    #[serde(default)]
    pub sni: Option<String>,
    /// ws Host header, defaults to address
    #[serde(default)]
    pub header_host: Option<String>,
    #[serde(default = "default_transport")]
    pub transport: String,
    #[serde(default = "default_name")]
    pub name: String,
}

fn default_port() -> u16 { 443 }
fn default_security() -> String { "tls".to_string() }
fn default_path() -> String { "/".to_string() }
fn default_transport() -> String { "ws".to_string() }
fn default_name() -> String { "cf-worker-edge".to_string() }

impl VlessProfile {
    pub fn new(uuid: String, address: String) -> Self {
        Self {
            uuid,
            address,
            port: 443,
            security: "tls".into(),
            path: "/".into(),
            sni: None,
            header_host: None,
            transport: "ws".into(),
            name: "cf-worker-edge".into(),
        }
    }

    pub fn effective_sni(&self) -> String {
        self.sni.clone().unwrap_or_else(|| self.address.clone())
    }

    pub fn effective_header_host(&self) -> String {
        self.header_host.clone().unwrap_or_else(|| self.address.clone())
    }

    /// A copy pointing at a local wrangler-dev worker (VPN-free testing).
    #[allow(dead_code)]
    pub fn local_ws(&self, lan_ip: &str, port: u16) -> Self {
        Self {
            uuid: self.uuid.clone(),
            address: lan_ip.to_string(),
            port,
            security: "none".into(),
            path: self.path.clone(),
            sni: None,
            header_host: Some(lan_ip.to_string()),
            transport: "ws".into(),
            name: "cf-worker-LOCAL (no VPN)".into(),
        }
    }

    /// The portable `vless://` URI used by client apps.
    pub fn share_link(&self) -> String {
        let params = [
            ("encryption", "none"),
            ("security", &self.security),
            ("type", &self.transport),
            ("sni", &self.effective_sni()),
            ("host", &self.effective_header_host()),
            ("path", &self.path),
            ("fp", "chrome"),
        ];
        let qs = params
            .iter()
            .map(|(k, v)| format!("{k}={}", url::form_urlencoded::byte_serialize(v.as_bytes()).collect::<String>()))
            .collect::<Vec<_>>()
            .join("&");
        let display = url::form_urlencoded::byte_serialize(self.name.as_bytes()).collect::<String>();
        format!(
            "vless://{}@{}:{}?{}#{}",
            self.uuid, self.address, self.port, qs, display
        )
    }

    /// A full xray client config (inbound socks/http + VLESS outbound).
    pub fn xray_client_json(&self) -> String {
        use serde_json::json;
        let tls_settings = if self.security == "tls" {
            json!({ "serverName": self.effective_sni(), "fingerprint": "chrome" })
        } else {
            json!(null)
        };
        let ws_settings = json!({
            "path": self.path,
            "headers": { "Host": self.effective_header_host() }
        });
        let cfg = json!({
            "log": { "loglevel": "warning" },
            "inbounds": [
                { "tag": "socks-in", "listen": "127.0.0.1", "port": 10808,
                  "protocol": "socks", "settings": { "auth": "noauth", "udp": true } },
                { "tag": "http-in", "listen": "127.0.0.1", "port": 10809,
                  "protocol": "http" }
            ],
            "outbounds": [{
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": self.address,
                        "port": self.port,
                        "users": [{ "id": self.uuid, "encryption": "none" }]
                    }]
                },
                "streamSettings": {
                    "network": self.transport,
                    "security": self.security,
                    "tlsSettings": tls_settings,
                    "wsSettings": ws_settings
                }
            }]
        });
        serde_json::to_string_pretty(&cfg).unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn share_link_encoding() {
        let p = VlessProfile::new(
            "abc-123".into(),
            "myhost.workers.dev".into(),
        );
        let link = p.share_link();
        assert!(link.starts_with("vless://abc-123@myhost.workers.dev:443?"));
        assert!(link.contains("security=tls"));
        assert!(link.contains("type=ws"));
        assert!(link.contains("sni=myhost.workers.dev"));
        assert!(link.contains("#cf-worker-edge"));
    }

    #[test]
    fn rewrite_keeps_uuid_and_query() {
        let p = VlessProfile::new(
            "uuid-1".into(),
            "orig.workers.dev".into(),
        );
        let link = p.share_link();
        let rewritten = super::rewrite_vless_with_endpoint(&link, "1.2.3.4:8443");
        assert!(rewritten.contains("vless://uuid-1@1.2.3.4:8443"));
        // the name fragment survives
        assert!(rewritten.contains("#cf-worker-edge"));
    }
}

/// Point a vless link at a clean IP:port (drop any hostname/port).
pub fn rewrite_vless_with_endpoint(vless_link: &str, endpoint: &str) -> String {
    let body = match vless_link.strip_prefix("vless://") {
        Some(b) => b,
        None => return vless_link.to_string(),
    };

    // fragment (#)
    let (body, frag) = match body.find('#') {
        Some(i) => (&body[..i], &body[i..]),
        None => (body, ""),
    };
    // query (?)
    let (body, query) = match body.find('?') {
        Some(i) => (&body[..i], &body[i..]),
        None => (body, ""),
    };
    // user @ hostport
    let (user, _hostport) = match body.rfind('@') {
        Some(i) => (&body[..i], &body[i + 1..]),
        None => ("", body),
    };

    let (ip, port): (String, String) = match endpoint.rpartition(':') {
        Some((ip, port)) if port.chars().all(|c| c.is_ascii_digit()) => {
            (ip.to_string(), port.to_string())
        }
        _ => (endpoint.to_string(), String::new()),
    };

    let new_hostport = if port.is_empty() {
        endpoint.to_string()
    } else {
        format!("{ip}:{port}")
    };

    format!("vless://{user}@{new_hostport}{query}{frag}")
}

trait Rpartition<'a> {
    fn rpartition(&self, pat: char) -> Option<(&'a str, &'a str)>;
}

impl<'a> Rpartition<'a> for &'a str {
    fn rpartition(&self, pat: char) -> Option<(&'a str, &'a str)> {
        self.rfind(pat).map(|i| (&self[..i], &self[i + 1..]))
    }
}
