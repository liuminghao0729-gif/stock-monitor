"""Vercel 函数的通用逻辑:每个 api/xxx.py 里的 handler 类调用 serve(self, 'xxx')。"""
import json, os, sys
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(__file__))
import _core as core


def serve(h, name):
    q = {k: v[0] for k, v in parse_qs(urlparse(h.path).query).items()}
    code, data, age = core.route(name, q)
    h.send_response(code)
    h.send_header("Content-Type", "application/json")
    h.send_header("Cache-Control", f"public, s-maxage={age}, stale-while-revalidate={age}" if age else "no-store")
    h.end_headers()
    h.wfile.write(json.dumps(data).encode())
