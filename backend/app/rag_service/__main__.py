"""Allow `python -m app.rag_service` to start the server."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).resolve().parents[2])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_BACKEND_DIR, ".env"))
except ImportError:
    pass

from app.rag_service.server import main

if __name__ == "__main__":
    main()
