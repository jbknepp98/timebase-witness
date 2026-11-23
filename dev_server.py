"""Local preview: serves site/ on 127.0.0.1:$PORT (default 8790), swapping in dev-config.json (broker = the Mac Mini)."""
import http.server, os, functools
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
DEV_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dev-config.json")
class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/config.json":
            data = open(DEV_CFG, "rb").read()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        super().do_GET()
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache"); super().end_headers()
http.server.ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8790"))), functools.partial(H, directory=ROOT)).serve_forever()
