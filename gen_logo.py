#!/usr/bin/env python3
"""Generate the Khvarenah logo via the Gemini image model."""
import base64, json, pathlib, re, urllib.request

ENV = pathlib.Path.home() / ".hermes" / ".env"
KEY = None
for line in ENV.read_text().splitlines():
    if line.startswith("GOOGLE_API_KEY="):
        KEY = line.split("=", 1)[1].strip().strip('"')

assert KEY, "GOOGLE_API_KEY not found"

PROMPT = (
    "A luxurious minimal app logo emblem for an Iranian VPN tool named Khvarenah "
    "(ancient Persian royal glory and radiance). A radiant symmetrical golden winged "
    "solar emblem inspired by Persian royal glory, with elegant abstract wings "
    "sweeping outward from a central stylized Persian K monogram, elongated flames "
    "of sacred divine fire rising subtly behind it. Metallic gold gradient on a "
    "solid pure black background. Premium flat vector style, ultra-clean crisp "
    "geometric shapes, subtle warm glow and halo, high contrast, no text, no "
    "letters other than the abstract K monogram, centered composition, square canvas."
)

url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={KEY}"
body = json.dumps({
    "contents": [{"parts": [{"text": PROMPT}]}],
    "generationConfig": {"responseModalities": ["IMAGE"]},
}).encode()

req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=180) as r:
    d = json.load(r)

out = pathlib.Path("khvarenah/assets")
out.mkdir(parents=True, exist_ok=True)

saved = False
for cand in d.get("candidates", []):
    for p in cand.get("content", {}).get("parts", []):
        if "inlineData" in p:
            b64 = p["inlineData"]["data"]
            mime = p["inlineData"].get("mimeType", "image/png")
            ext = "png" if "png" in mime else "jpg"
            (out / f"khvarenah.{ext}").write_bytes(base64.b64decode(b64))
            print(f"SAVED khvarenah/assets/khvarenah.{ext} ({len(b64)} b64, {mime})")
            saved = True
if not saved:
    print("NO IMAGE. Response:", json.dumps(d)[:1000])
