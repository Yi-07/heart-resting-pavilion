"""fillers 预生成等待语音(backend-plan §2 voice 行)。

分析等待期(停采→精稿之间)直发文件零运行时合成;与 TTS 同音色(sidecar 同源)。
生成:uv run python -m app.voice.fillers(幂等,已存在跳过;换音色删目录重跑)。
网关/图内经 pick() 取一发给 emitter.audio。
"""

from __future__ import annotations

import random
from pathlib import Path

from app import config
from app import logger as app_logger
from app.voice.tts import synthesize

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="fillers")

FILLERS: dict[str, str] = {
    "wait_1": "我在呢,正在把你说的都梳理进黑板,别急。",
    "wait_2": "快好了,再陪我等一小会儿。",
}


def _dir() -> Path:
    return Path(config.FILLERS_DIR)


def generate() -> None:
    """把全部 filler 话术合成为 wav 落盘(幂等)。"""
    _dir().mkdir(parents=True, exist_ok=True)
    for name, text in FILLERS.items():
        path = _dir() / f"{name}.wav"
        if path.exists():
            print(f"skip {path}(已存在)")
            continue
        wav = synthesize(text)
        if wav is None:
            print(f"FAIL {name}: TTS 不可用(先确认 sidecar/模型就绪)")
            continue
        path.write_bytes(wav)
        print(f"ok {path} ({len(wav)} bytes)")


def pick() -> bytes | None:
    """随机取一条等待语音 wav;目录为空返回 None(调用方跳过)。"""
    files = sorted(_dir().glob("wait_*.wav"))
    if not files:
        return None
    return random.choice(files).read_bytes()


if __name__ == "__main__":
    generate()
