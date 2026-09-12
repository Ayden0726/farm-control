"""Docker healthcheck — exit 0 once the API is serving /health."""
from __future__ import annotations

import sys
import urllib.error
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
        sys.exit(0 if getattr(response, "status", 200) == 200 else 1)
except (urllib.error.URLError, TimeoutError, OSError):
    sys.exit(1)
