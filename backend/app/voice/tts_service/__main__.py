"""Allow `python -m app.voice.tts_service` to start the server."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 确保 backend/ 在 sys.path,使 app.* 包导入可用
_BACKEND_DIR = str(Path(__file__).resolve().parents[3])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# 加载 .env (TTS_SERVICE_PORT 等)
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_BACKEND_DIR, ".env"))
except ImportError:
    pass

from app.voice.tts_service.server import main

if __name__ == "__main__":
    main()
