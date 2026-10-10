"""服务配置:环境变量 → 冻结配置对象。

单源原则:所有可调项只在这里出现一次,engine / server 只读 Settings 实例。
默认值取自本机实测最优参数(cut5 + min_chunk_length=16 + overlap_length=2 +
streaming_mode=True + seed=42),改这里即可,不必碰引擎代码。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# GPT-SoVITS 的 yaml 与 reference 全部是相对路径,进程工作目录必须是仓库根。
ROOT = Path(__file__).resolve().parent.parent

REF_DIR = ROOT / "reference"
VOICE_NAME_FILE = REF_DIR / "my_voice.txt"
VOICE_LIST_FILE = REF_DIR / "voice_list.json"


def _env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # ---- 网络 ----
    host: str
    port: int
    auth_token: str
    log_level: str

    # ---- 模型 ----
    tts_config: str
    version: str
    voice: str
    ref_audio_path: str
    prompt_text: str
    prompt_lang: str

    # ---- 推理参数(本机实测最优)----
    text_lang: str
    text_split_method: str
    streaming_mode: bool
    min_chunk_length: int
    overlap_length: int
    seed: int
    parallel_infer: bool
    repetition_penalty: float
    speed_factor: float
    fragment_interval: float
    top_k: int
    top_p: float
    temperature: float

    # ---- 护栏 ----
    max_text_len: int
    max_sentences: int
    max_audio_bytes: int
    max_sentence_chars: int
    queue_wait_timeout_s: float

    voices: dict[str, str] = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return ROOT

    @property
    def ref_dir(self) -> Path:
        return REF_DIR


def _load_voices() -> dict[str, str]:
    """音色名 → 参考音频文本。读不到就返回空 dict,服务仍可用(显式指定音色时)。"""
    try:
        return json.loads(VOICE_LIST_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _default_voice() -> str:
    try:
        return VOICE_NAME_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """构建配置(进程内单例)。"""
    voices = _load_voices()
    voice = _env_str("GPT_SOVITS_VOICE") or _default_voice()

    # 参考音频:显式路径 > 音色名映射。两者都没有时留空,由 engine 在就绪时报错,
    # 而不是像 api_v2.py 那样读一个不存在的 yaml 再静默覆盖。
    ref_audio = _env_str("GPT_SOVITS_REF_AUDIO")
    if not ref_audio and voice:
        ref_audio = f"reference/{voice}.wav"

    prompt_text = _env_str("GPT_SOVITS_PROMPT_TEXT") or voices.get(voice, "")

    return Settings(
        # ---- 网络 ----
        host=_env_str("TTS_SERVICE_HOST", "127.0.0.1"),
        port=_env_int("TTS_SERVICE_PORT", 9001),
        auth_token=_env_str("SERVICE_AUTH_TOKEN"),
        log_level=_env_str("TTS_LOG_LEVEL", "INFO"),
        # ---- 模型 ----
        tts_config=_env_str("GPT_SOVITS_CONFIG", "GPT_SoVITS/configs/tts_infer.yaml"),
        version=_env_str("GPT_SOVITS_VERSION", "v2"),
        voice=voice,
        ref_audio_path=ref_audio,
        prompt_text=prompt_text,
        prompt_lang=_env_str("GPT_SOVITS_PROMPT_LANG", "zh"),
        # ---- 推理参数 ----
        text_lang=_env_str("GPT_SOVITS_TEXT_LANG", "zh"),
        text_split_method=_env_str("GPT_SOVITS_SPLIT_METHOD", "cut5"),
        streaming_mode=_env_bool("GPT_SOVITS_STREAMING", True),
        min_chunk_length=_env_int("GPT_SOVITS_MIN_CHUNK", 16),
        overlap_length=_env_int("GPT_SOVITS_OVERLAP", 2),
        seed=_env_int("GPT_SOVITS_SEED", 42),
        parallel_infer=_env_bool("GPT_SOVITS_PARALLEL_INFER", True),
        repetition_penalty=_env_float("GPT_SOVITS_REPETITION_PENALTY", 1.35),
        speed_factor=_env_float("GPT_SOVITS_SPEED", 1.0),
        fragment_interval=_env_float("GPT_SOVITS_FRAGMENT_INTERVAL", 0.3),
        top_k=_env_int("GPT_SOVITS_TOP_K", 5),
        top_p=_env_float("GPT_SOVITS_TOP_P", 1.0),
        temperature=_env_float("GPT_SOVITS_TEMPERATURE", 1.0),
        # ---- 护栏 ----
        # 上游对文本长度、音频字节数都没有任何限制,单次请求可以打满显存。
        max_text_len=_env_int("GPT_SOVITS_MAX_TEXT", 2000),
        max_sentences=_env_int("GPT_SOVITS_MAX_SENTENCES", 60),
        max_audio_bytes=_env_int("GPT_SOVITS_MAX_AUDIO_BYTES", 8 * 1024 * 1024),
        max_sentence_chars=_env_int("GPT_SOVITS_MAX_SENT_CHARS", 30),
        queue_wait_timeout_s=_env_float("GPT_SOVITS_QUEUE_WAIT_S", 120.0),
        voices=voices,
    )
