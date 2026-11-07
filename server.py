"""本地预览服务器:提供网页文件 + /api 数据接口。运行:python3 server.py"""
import json, os, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "api"))
import core


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def do_GET(self):
        u = urlparse(self.path)
        if not u.path.startswith("/api/"):
            return super().do_GET()
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            name = u.path[5:]
            if name == "quotes":
                out = core.quotes([s for s in q.get("symbols", "").split(",") if s][:60])
            elif name == "bars":
                out = core.bars(q["symbol"], q.get("range", "6M"))
            elif name == "news":
                out = core.news(q.get("symbol", ""))
            elif name == "earnings":
                out = core.earnings(q["date"])
            elif name == "status":
                out = {"finnhub": bool(os.environ.get("FINNHUB_KEY"))}
            else:
                self.send_error(404); return
            body, code = json.dumps(out).encode(), 200
        except Exception as e:
            body, code = json.dumps({"error": str(e)}).encode(), 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("网站已启动:http://127.0.0.1:5173  (按 Ctrl+C 停止)")
    print("Finnhub Key:", "已设置" if os.environ.get("FINNHUB_KEY") else "未设置(新闻和财报日历暂不可用)")
    ThreadingHTTPServer(("127.0.0.1", 5173), H).serve_forever()
