"""Remote 模式 ML 依赖隔离验证。

确认 remote 模式下主服务进程不导入 torch/funasr/chromadb 等重包。
通过子进程执行,避免测试进程自身的 import 干扰。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ML_PACKAGES = [
    "torch",
    "funasr",
    "cosyvoice",
    "chromadb",
    "sentence_transformers",
    "torchaudio",
    "jieba",
    "numpy",
]

BACKEND_DIR = Path(__file__).resolve().parents[1]

_CHECK_SCRIPT = '''\
"""检查 remote 模式 import 是否加载 ML 包。"""
import os, sys

os.environ["TTS_MODE"] = "remote"
os.environ["ASR_MODE"] = "remote"
os.environ["RAG_MODE"] = "remote"
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-for-isolation-check")

ml_packages = set(sys.argv[1:])
before = set(sys.modules.keys()) & ml_packages

# 触发完整 import chain
from app import config  # noqa: F401
from app.voice import tts  # noqa: F401
from app.voice import asr  # noqa: F401
import app.rag  # noqa: F401

after = set(sys.modules.keys()) & ml_packages
new_imports = sorted(after - before)
if new_imports:
    print(f"FAIL: {','.join(new_imports)}")
    sys.exit(1)
else:
    print("OK")
    sys.exit(0)
'''


def test_remote_mode_no_ml_imports():
    """remote 模式下主服务不导入 ML 重包。"""
    result = subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT, *ML_PACKAGES],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(BACKEND_DIR),
    )
    output = result.stdout.strip()
    if result.returncode != 0:
        pytest.fail(
            f"Remote 模式意外导入了 ML 模块:\n"
            f"stdout: {output}\n"
            f"stderr: {result.stderr[-500:] if result.stderr else ''}"
        )
    assert output == "OK"
