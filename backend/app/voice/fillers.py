"""预置话术语音(backend-plan §2 voice 行;spec L6「预置语音」行)。

固定话术(危机 P10/P11/黑板注 P12 · 等待语音 P7 · 心情回执 P13)预生成 wav,
运行时随文本同步直发,不占运行时 TTS;与 TTS 同音色(sidecar 同源)。
生成:uv run python -m app.voice.fillers(幂等,已存在跳过;换音色删目录重跑)。
话术正文单源在 phrases.py——本表只记「话术键→文案」映射,新增话术改两处一致。
网关/图内经 pick()/pick_named() 取用;缺文件跳过(音频缺席不影响文字链路)。
"""

from __future__ import annotations

import random
from pathlib import Path

from app import config
from app import logger as app_logger
from app.router import phrases
from app.schema import MoodKey
from app.voice.tts import synthesize

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="fillers")

# 通用「话术→wav」表:键=文件名干(组名_序号/名称),值=文案。
# 等待语音(P7)与心情回执(P13)按 phrases 单源展开;危机话术由网关按名直取。
FILLERS: dict[str, str] = {
    "wait_1": phrases.WAIT_SOOTHE,
    "wait_2": "快好了,再陪我等一小会儿。",
    **{f"mood_{mood}": text for mood, text in phrases.MOOD_ACK.items()},
    "crisis_soothe": phrases.CRISIS_SOOTHE,
    "crisis_hotline": phrases.CRISIS_HOTLINE,
}


def _dir() -> Path:
    return Path(config.FILLERS_DIR)


def generate() -> None:
    """把全部预置话术合成为 wav 落盘(幂等)。"""
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


def pick_named(name: str) -> bytes | None:
    """按名取预置语音(危机 P10/P11 · 心情回执 P13);缺文件返回 None。"""
    path = _dir() / f"{name}.wav"
    if not path.exists():
        return None
    return path.read_bytes()


def mood_ack_name(mood: MoodKey) -> str:
    """心情回执 wav 文件名(P13 六档与 MOOD_ACK 键同源)。"""
    return f"mood_{mood}"


if __name__ == "__main__":
    generate()
