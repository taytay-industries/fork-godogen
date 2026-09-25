#!/usr/bin/env python3
"""One-shot page for a user to paste an API key into ~/.config/godogen/env — for when they reach the agent
only remotely (no terminal) and the key must not pass through the chat.

    keydrop.py ELEVENLABS_API_KEY [--port 8765] [--minutes 30]

Listens on 127.0.0.1 under a random token path (printed as `PATH /k/<token>`); put it behind HTTPS the user can
reach (e.g. `tailscale serve --bg --https=8443 http://localhost:8765`), give them that URL, and turn the proxy off
afterwards. The key is checked with its service first (ELEVENLABS, TRIPO, XAI, GEMINI/GOOGLE), saved at 0600,
and never printed or logged. After one successful save — or after --minutes — the server exits.
"""
import argparse
import html
import os
import re
import secrets
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ENV = Path.home() / ".config/godogen/env"
VAR = ""   # set from the command line
TOKEN = secrets.token_urlsafe(24)
KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{20,200}$")

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Key drop</title>
<style>
:root{--bg:#f4f6f7;--card:#fff;--ink:#16252b;--muted:#5b6b71;--accent:#2f8f93;--bad:#b3261e;--good:#1e7b43}
@media (prefers-color-scheme:dark){:root{--bg:#0f1719;--card:#182326;--ink:#e6eef0;--muted:#9fb0b5;--accent:#5cc3c7;--bad:#ff8a80;--good:#7fd99b}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;padding:16px;box-sizing:border-box}
main{background:var(--card);border-radius:14px;padding:28px;max-width:440px;width:100%;box-shadow:0 2px 12px #0002}
h1{font-size:1.25rem;margin:0 0 6px}p{color:var(--muted);margin:0 0 18px}
input{width:100%;box-sizing:border-box;padding:12px;border-radius:8px;border:1px solid var(--muted);background:transparent;color:var(--ink);font:inherit}
button{margin-top:14px;width:100%;padding:12px;border:0;border-radius:8px;background:var(--accent);color:#fff;font:600 16px system-ui}
.msg{margin-top:16px;font-weight:600}.bad{color:var(--bad)}.good{color:var(--good)}
</style></head><body><main>
<h1>{var}</h1>
<p>Saved to <code>~/.config/godogen/env</code> on {host}. It is checked with its service first and never shown or logged.</p>
{body}
</main></body></html>"""

FORM = """<form method="post" autocomplete="off">
<input type="password" name="key" placeholder="Paste key" autofocus required spellcheck="false">
<button>Check and save</button></form>{msg}"""


# A cheap authenticated read per service: 200 means the key works.
CHECKS = {
    "ELEVENLABS": ("ElevenLabs", "https://api.elevenlabs.io/v1/user", lambda k: {"xi-api-key": k}),
    "TRIPO": ("Tripo", "https://api.tripo3d.ai/v2/openapi/user/balance", lambda k: {"Authorization": f"Bearer {k}"}),
    "XAI": ("xAI", "https://api.x.ai/v1/api-key", lambda k: {"Authorization": f"Bearer {k}"}),
    "GEMINI": ("Gemini", "https://generativelanguage.googleapis.com/v1beta/models", lambda k: {"x-goog-api-key": k}),
    "GOOGLE": ("Gemini", "https://generativelanguage.googleapis.com/v1beta/models", lambda k: {"x-goog-api-key": k}),
}


def check_key(key: str) -> tuple[bool, str]:
    check = CHECKS.get(VAR.split("_")[0])
    if not check:
        return True, "No check known for this variable; saved as given."
    name, url, headers = check
    req = urllib.request.Request(url, headers=headers(key))
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True, f"{name} accepted the key."
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace").lower()
        if name == "ElevenLabs" and e.code == 401 and "permission" in body:
            return True, "Key works, but lacks User: Read, so credits can't be shown. Saved anyway."
        return False, f"{name} rejected this key (HTTP {e.code}). Nothing was saved."
    except Exception:
        return False, f"Couldn't reach {name} to check the key. Nothing was saved."


def save_key(key: str) -> None:
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [l for l in lines if not re.match(rf"^\s*(export\s+)?{VAR}=", l)]
    lines.append(f"export {VAR}={key}")
    ENV.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ENV.parent, prefix=".env.")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV)


class Handler(BaseHTTPRequestHandler):
    server_version = "keydrop"
    sys_version = ""

    def log_message(self, fmt, *args):
        print(f"{self.command} {'/k/<token>' if TOKEN in self.path else self.path} -> {args[1] if len(args) > 1 else ''}", flush=True)

    def send(self, code: int, body: str):
        data = PAGE.replace("{var}", html.escape(VAR)).replace("{host}", html.escape(os.uname().nodename)).replace("{body}", body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self) -> bool:
        if self.path.rstrip("/") == f"/k/{TOKEN}":
            return True
        self.send(404, "<p>Not found.</p>")
        return False

    def do_GET(self):
        if self.authorized():
            self.send(200, FORM.replace("{msg}", ""))

    def do_POST(self):
        if not self.authorized():
            return
        n = min(int(self.headers.get("Content-Length") or 0), 4096)
        key = urllib.parse.parse_qs(self.rfile.read(n).decode(errors="replace")).get("key", [""])[0].strip()
        if not KEY_RE.match(key):
            self.send(400, FORM.replace("{msg}", '<p class="msg bad">That doesn\'t look like an API key.</p>'))
            return
        ok, note = check_key(key)
        if not ok:
            self.send(400, FORM.replace("{msg}", f'<p class="msg bad">{html.escape(note)}</p>'))
            return
        save_key(key)
        del key
        self.send(200, f'<p class="msg good">Saved. {html.escape(note)}</p><p>This page is now closed. You can tell Claude it\'s done.</p>')
        print("SAVED", flush=True)
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def main():
    global VAR
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("var", help="environment variable to set, e.g. ELEVENLABS_API_KEY")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--minutes", type=float, default=30)
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", a.var):
        sys.exit("var must look like NAME_API_KEY")
    VAR = a.var
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    threading.Timer(a.minutes * 60, srv.shutdown).start()
    print(f"PATH /k/{TOKEN}", flush=True)
    srv.serve_forever()
    print("EXIT", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
