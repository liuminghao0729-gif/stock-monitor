"""Vercel 函数的通用外壳:每个 api/xxx.py 只需一行调用 make('xxx')。"""
import json, os, sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(__file__))
import _core as core


def make(name):
    class handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            code, data, age = core.route(name, q)
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", f"public, s-maxage={age}, stale-while-revalidate={age}" if age else "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
    return handler
