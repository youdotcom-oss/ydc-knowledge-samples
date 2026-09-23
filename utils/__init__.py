"""Shared helpers for the demos: rendering, synthesis, cost, and latency.

Importing this package loads .env, so a bare ``You()`` picks up YDC_API_KEY.
"""

import os
import sys

from utils.env import load_env

load_env()

if not (os.environ.get("YDC_API_KEY") or os.environ.get("YOU_API_KEY_AUTH")):
    sys.exit("Missing YDC_API_KEY. Copy .env.example to .env and set it.")
