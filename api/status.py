import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from http.server import BaseHTTPRequestHandler
from _vercel import serve


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        serve(self, "status")
