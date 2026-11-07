"""本地预览服务器:提供网页文件(public/)+ /api 数据接口。运行:python3 server.py"""
import json, os, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "api"))
import _core as core


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=os.path.join(ROOT, "public"), **k)

    def do_GET(self):
        u = urlparse(self.path)
        if not u.path.startswith("/api/"):
            return super().do_GET()
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        code, data, _ = core.route(u.path[5:], q)
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("网站已启动:http://127.0.0.1:5173  (按 Ctrl+C 停止)")
    print("Finnhub Key:", "已设置" if os.environ.get("FINNHUB_KEY") else "未设置(新闻和财报日历暂不可用)", "| FMP Key:", "已设置" if os.environ.get("FMP_KEY") else "未设置(目标价、评级变动、涨跌榜暂不可用)")
    ThreadingHTTPServer(("127.0.0.1", 5173), H).serve_forever()
