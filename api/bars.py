import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _vercel import make
handler = make("bars")
