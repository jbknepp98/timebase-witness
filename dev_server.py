"""Local preview: serves site/ on 127.0.0.1:$PORT (default 8790), swapping in dev-config.json.

HTTP calls to /api/ are forwarded to the gateway named by opcuaGateway in dev-config.json, so the page's
REST calls (connections, Handoffs, briefs) work without CORS. The live stream still connects to
the gateway directly over WebSocket.
"""
import functools, http.server, json, os, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "site")
DEV_CFG = os.path.join(HERE, "dev-config.json")


def gateway_base():
    try:
        ws = json.load(open(DEV_CFG)).get("opcuaGateway", "")
    except (OSError, ValueError):
        return ""
    u = urllib.parse.urlsplit(ws)
    return f"{'https' if u.scheme == 'wss' else 'http'}://{u.netloc}" if u.netloc else ""


class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/config.json":
            data = open(DEV_CFG, "rb").read()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        if self.path.startswith("/api/"):
            return self.forward()
        super().do_GET()

    def do_POST(self): self.forward()
    def do_PUT(self): self.forward()
    def do_DELETE(self): self.forward()

    def forward(self):
        base = gateway_base()
        if not base or not self.path.startswith("/api/"):
            self.send_error(404); return
        n = int(self.headers.get("Content-Length") or 0)
        req = urllib.request.Request(base + self.path, data=self.rfile.read(n) if n else None, method=self.command)
        if self.headers.get("Content-Type"):
            req.add_header("Content-Type", self.headers["Content-Type"])
        try:
            r = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            r = e
        except OSError as e:
            self.send_error(502, str(e)); return
        self.send_response(r.status)
        for k in ("Content-Type", "Content-Disposition"):
            if r.headers.get(k):
                self.send_header(k, r.headers[k])
        self.end_headers()
        while chunk := r.read(8192):  # streamed, so the agent's progress events arrive as they happen
            self.wfile.write(chunk); self.wfile.flush()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache"); super().end_headers()


http.server.ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8790"))), functools.partial(H, directory=ROOT)).serve_forever()
