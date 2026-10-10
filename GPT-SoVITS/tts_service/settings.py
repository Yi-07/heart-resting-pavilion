"""服务配置:CLI > ENV > YAML > default 四级优先级,冻结成 Settings 对象。

单源原则:所有可调项只在这里出现一次,engine / server 只读 Settings 实例。

为什么引入 YAML(plan §36 H1):
    原来全部默认值硬编码在本文件里,改一个推理参数要动代码。而这套服务要同时
    跑在 `conda gpt-sovite-v2`(有 torch/CUDA)里,推理参数是本机标定的 ——
    让它们落在一个能单独替换、不改代码的文件里,换机器/换音色才不用改代码。

四级优先级(高 → 低):
    CLI   --host / --port / ...        一次性启动参数,最高
    ENV   GPT_SOVITS_* / TTS_*         容器/CI 注入
    YAML  tts_service/config.yaml      本机标定值(主配置源)
    硬编码 default                     保底,保证缺文件也能起

**每一层的存在都要能被单独验证**,所以优先级由 `_resolve()` 一处实现,
不散落在各处 `os.environ.get(...) or yaml.get(...) or default` 里。

注:`GPT_SOVITS_CONFIG` 是**上游推理配置**(tts_infer.yaml,权重路径都在里面),
与本文件的服务配置是两回事,不要混。本服务自己的配置文件是
`tts_service/config.yaml`,由 `GPT_SOVITS_SERVICE_CONFIG` 指定路径。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

# GPT-SoVITS 的 yaml 与 reference 全部是相对路径,进程工作目录必须是仓库根。
ROOT = Path(__file__).resolve().parent.parent

REF_DIR = ROOT / "reference"
VOICE_NAME_FILE = REF_DIR / "my_voice.txt"
VOICE_LIST_FILE = REF_DIR / "voice_list.json"

SERVICE_CONFIG_FILE = Path(__file__).resolve().parent / "config.yaml"
"""本服务配置主源。路径可由 GPT_SOVITS_SERVICE_CONFIG 覆盖(便于并行实验)。"""


# ---- 配置项声明表 ----
# 一行一个可调项,四个字段:Settings 属性名 / ENV 变量 / YAML 点路径 / 类型。
# default 挂在 FIELDS 里而不是散在 get_settings 的参数列表上 —— 那样"加一项要改
# 两处",漏一处不会报错、只会静默用错值。
FieldKind = Literal["str", "int", "float", "bool"]


@dataclass(frozen=True)
class Field:
    name: str
    env: str
    yaml_path: str
    kind: FieldKind
    default: Any
    doc: str


FIELDS: tuple[Field, ...] = (
    # ---- 网络 ----
    Field("host", "TTS_SERVICE_HOST", "service.host", "str", "127.0.0.1", "监听地址"),
    Field("port", "TTS_SERVICE_PORT", "service.port", "int", 9001, "监听端口"),
    Field("auth_token", "SERVICE_AUTH_TOKEN", "service.auth_token", "str", "", "Bearer 认证 token;空=不校验"),
    Field("log_level", "TTS_LOG_LEVEL", "service.log_level", "str", "INFO", "日志级别"),
    Field("gpu_poll_enabled", "TTS_GPU_POLL_ENABLED", "service.gpu_poll_enabled", "bool", True,
          "后台 GPU 轮询;关掉则完全不执行 nvidia-smi(plan §36 F1 的 off 档)"),
    # ---- 日志 ----
    Field("log_dir", "TTS_LOG_DIR", "service.log_dir", "str", "logs",
          "日志文件目录;相对路径锚定 GPT-SoVITS 仓库根(非进程 cwd)"),
    Field("log_file_level", "TTS_LOG_FILE_LEVEL", "service.log_file_level", "str", "INFO",
          "文件日志级别(与终端分开);DEBUG 会写入 torio/asyncio 等第三方噪声"),
    Field("log_rotation", "TTS_LOG_ROTATION", "service.log_rotation", "str", "10 MB",
          "单日志文件轮转大小"),
    Field("log_retention", "TTS_LOG_RETENTION", "service.log_retention", "str", "30 days",
          "日志文件保留时长"),
    # ---- 模型 ----
    Field("tts_config", "GPT_SOVITS_CONFIG", "model.tts_config", "str",
          "GPT_SoVITS/configs/tts_infer.yaml", "上游推理配置(权重路径,相对仓库根)"),
    Field("version", "GPT_SOVITS_VERSION", "model.version", "str", "v2", "模型版本"),
    Field("voice", "GPT_SOVITS_VOICE", "model.voice", "str", "", "默认音色名(空则读 my_voice.txt)"),
    Field("ref_audio_path", "GPT_SOVITS_REF_AUDIO", "model.ref_audio_path", "str", "",
          "参考音频路径(空则由 voice 推导 reference/<voice>.wav)"),
    Field("prompt_text", "GPT_SOVITS_PROMPT_TEXT", "model.prompt_text", "str", "",
          "参考音频对应文本(空则由 voice 查 voice_list.json)"),
    Field("prompt_lang", "GPT_SOVITS_PROMPT_LANG", "model.prompt_lang", "str", "zh", "参考音频语种"),
    # ---- 推理参数(本机实测最优)----
    Field("text_lang", "GPT_SOVITS_TEXT_LANG", "inference.text_lang", "str", "zh", "合成文本语种"),
    Field("text_split_method", "GPT_SOVITS_SPLIT_METHOD", "inference.text_split_method", "str",
          "cut5", "上游切句方法"),
    Field("streaming_mode", "GPT_SOVITS_STREAMING", "inference.streaming_mode", "bool", True,
          "流式推理(关掉则整段合成,延迟显著变差)"),
    Field("min_chunk_length", "GPT_SOVITS_MIN_CHUNK", "inference.min_chunk_length", "int", 16,
          "最小语义块长度"),
    Field("overlap_length", "GPT_SOVITS_OVERLAP", "inference.overlap_length", "int", 2,
          "块间重叠长度"),
    Field("seed", "GPT_SOVITS_SEED", "inference.seed", "int", 42, "随机种子(固定=结果可复现)"),
    Field("parallel_infer", "GPT_SOVITS_PARALLEL_INFER", "inference.parallel_infer", "bool", True,
          "并行推理"),
    Field("repetition_penalty", "GPT_SOVITS_REPETITION_PENALTY", "inference.repetition_penalty",
          "float", 1.35, "重复惩罚"),
    Field("speed_factor", "GPT_SOVITS_SPEED", "inference.speed_factor", "float", 1.0, "语速"),
    Field("fragment_interval", "GPT_SOVITS_FRAGMENT_INTERVAL", "inference.fragment_interval",
          "float", 0.3, "分片间隔(秒);同时决定句末静音填充长度"),
    Field("top_k", "GPT_SOVITS_TOP_K", "inference.top_k", "int", 5, "采样 top_k"),
    Field("top_p", "GPT_SOVITS_TOP_P", "inference.top_p", "float", 1.0, "采样 top_p"),
    Field("temperature", "GPT_SOVITS_TEMPERATURE", "inference.temperature", "float", 1.0, "采样温度"),
    # ---- 护栏 ----
    # 上游对文本长度、音频字节数都没有任何限制,单次请求可以打满显存。
    Field("max_text_len", "GPT_SOVITS_MAX_TEXT", "guard.max_text_len", "int", 2000, "单请求文本上限"),
    Field("max_sentences", "GPT_SOVITS_MAX_SENTENCES", "guard.max_sentences", "int", 60, "单请求分句数上限"),
    Field("max_audio_bytes", "GPT_SOVITS_MAX_AUDIO_BYTES", "guard.max_audio_bytes", "int",
          8 * 1024 * 1024, "单请求音频字节上限"),
    Field("max_sentence_chars", "GPT_SOVITS_MAX_SENT_CHARS", "guard.max_sentence_chars", "int", 30,
          "单句汉字数上限(分句护栏)"),
    Field("queue_wait_timeout_s", "GPT_SOVITS_QUEUE_WAIT_S", "guard.queue_wait_timeout_s", "float",
          120.0, "排队等推理锁的超时"),
)

_FIELD_BY_NAME: dict[str, Field] = {f.name: f for f in FIELDS}


# ---- 取值 ----


_TRUE_TOKENS = frozenset({"1", "true", "yes", "on", "y", "t", "enabled"})
_FALSE_TOKENS = frozenset({"0", "false", "no", "off", "n", "f", "disabled"})


def _coerce(raw: Any, kind: FieldKind, field_name: str) -> Any:
    """把 YAML/ENV/CLI 的原始值转成声明类型;转不动就用该项的 default。

    静默回退而不是抛异常:一个手滑的 `min_chunk_length: "sixteen"` 不该让服务起不来,
    但也不该悄悄生效 —— 所以回退时打一条 WARN,让错配在启动日志里可见。

    **bool 必须显式两分**:上一版写的是 `x in ("1","true","yes","on")`,于是
    `"typo"`、`"off"`、`"maybe"` 全都落进 False 分支 —— 一个拼错的
    `gpu_poll_enabled` 会**静默关掉 GPU 轮询**,而配置看起来"读到了"。
    现在只认 _TRUE_TOKENS / _FALSE_TOKENS 两个白名单,其余一律回退 default 并告警。
    """
    if kind == "bool":
        # 先按 str 归一:bool 本身、YAML 的 true/false、ENV 的 1/0 都走这条路
        token = str(raw).strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
        import logging

        logging.getLogger("tts_service").warning(
            "config_bool_invalid field=%s value=%r -> default=%r "
            "(合法真值 %s / 合法假值 %s)",
            field_name,
            raw,
            _FIELD_BY_NAME[field_name].default,
            sorted(_TRUE_TOKENS),
            sorted(_FALSE_TOKENS),
        )
        return bool(_FIELD_BY_NAME[field_name].default)

    try:
        if kind == "str":
            return str(raw).strip()
        if kind == "int":
            return int(raw)
        return float(raw)
    except (TypeError, ValueError):
        import logging

        logging.getLogger("tts_service").warning(
            "config_coerce_fallback field=%s value=%r kind=%s -> default",
            field_name,
            raw,
            kind,
        )
        return _FIELD_BY_NAME[field_name].default


def _yaml_lookup(tree: Mapping[str, Any], dotted: str) -> Any:
    """按点路径取值:'service.host' → tree['service']['host'];缺任一层返回 None。"""
    cur: Any = tree
    for part in dotted.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return None
        cur = cur[part]
    return cur


@lru_cache(maxsize=4)
def _load_yaml(path: str) -> Mapping[str, Any]:
    """读 YAML 主配置。文件不存在/解析失败 → 空 dict(退回 default,服务仍可起)。"""
    import logging

    p = Path(path)
    if not p.is_file():
        logging.getLogger("tts_service").info(
            "config_yaml_absent path=%s(全部用 default)", p
        )
        return {}
    try:
        import yaml  # 重依赖懒加载:没有 YAML 也要能起

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 — 配置坏了不能拖垮启动,但必须报出来
        logging.getLogger("tts_service").error(
            "config_yaml_unreadable path=%s error=%s -> 全部用 default", p, exc
        )
        return {}
    if not isinstance(data, Mapping):
        logging.getLogger("tts_service").error(
            "config_yaml_not_mapping path=%s -> 全部用 default", p
        )
        return {}
    return data


def _resolve(
    f: Field, yaml_tree: Mapping[str, Any], cli: Mapping[str, Any] | None
) -> Any:
    """CLI > ENV > YAML > default。一处实现,便于单测逐层验证。"""
    if cli is not None and cli.get(f.name) is not None:
        return _coerce(cli[f.name], f.kind, f.name)
    env = os.environ.get(f.env)
    if env is not None and env.strip():
        return _coerce(env, f.kind, f.name)
    y = _yaml_lookup(yaml_tree, f.yaml_path)
    if y is not None:
        return _coerce(y, f.kind, f.name)
    return f.default


def _load_voices() -> Mapping[str, str]:
    """音色名 → 参考音频文本。读不到返回空(服务仍可用,显式指定音色时)。

    返回 **只读映射**而非 dict(plan §36 H2):Settings 是 frozen dataclass,
    但 frozen 只冻结属性绑定,不冻结容器内容 —— 可变 dict 挂上去,
    任何持有 Settings 的地方都能就地改,配置就不再是"冻结"的。
    """
    try:
        data = json.loads(VOICE_LIST_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return MappingProxyType({})
    if not isinstance(data, dict):
        return MappingProxyType({})
    return MappingProxyType({str(k): str(v) for k, v in data.items()})


def _default_voice() -> str:
    try:
        return VOICE_NAME_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@dataclass(frozen=True)
class Settings:
    # ---- 网络 ----
    host: str
    port: int
    auth_token: str
    log_level: str
    gpu_poll_enabled: bool
    """后台 GPU 轮询开关(plan §36 F1)。

    关掉它 `nvidia-smi` 就完全不被执行 —— 这是 A/B 的 off 档。默认开:
    health 已经只读缓存,轮询不占请求路径,10s 一次的 nvidia-smi 开销可忽略。
    """

    # ---- 日志 ----
    log_dir: str
    log_file_level: str
    log_rotation: str
    log_retention: str

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

    voices: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """只读映射(见 `_load_voices`)。Mapping 而非 dict:调用方不许就地改。"""

    config_sources: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """每项最终**来自哪一级**:cli / env / yaml / default。

    存在的理由:配置出错时最费时间的是"我改了为什么没生效"。启动日志里打一张
    来源表,一眼能看出该项是被更高优先级盖掉了,还是根本没读到。
    """

    @property
    def root(self) -> Path:
        return ROOT

    @property
    def ref_dir(self) -> Path:
        return REF_DIR


def _origin(f: Field, yaml_tree: Mapping[str, Any], cli: Mapping[str, Any] | None) -> str:
    """同一套优先级,只回答"这一项最终来自哪一级"。"""
    if cli is not None and cli.get(f.name) is not None:
        return "cli"
    env = os.environ.get(f.env)
    if env is not None and env.strip():
        return "env"
    if _yaml_lookup(yaml_tree, f.yaml_path) is not None:
        return "yaml"
    return "default"


def build_settings(cli: Mapping[str, Any] | None = None) -> Settings:
    """按 CLI > ENV > YAML > default 解析出 Settings(不缓存,便于测试)。"""
    yaml_path = os.environ.get("GPT_SOVITS_SERVICE_CONFIG", "").strip() or str(
        SERVICE_CONFIG_FILE
    )
    tree = _load_yaml(yaml_path)
    resolved = {f.name: _resolve(f, tree, cli) for f in FIELDS}
    origins = {f.name: _origin(f, tree, cli) for f in FIELDS}

    voices = _load_voices()

    # 参考音频:显式值 > YAML > 由 voice 推导。三级都空才留空,由 engine 就绪时报错,
    # 而不是像 api_v2.py 那样读一个不存在的 yaml 再静默覆盖。
    voice = resolved["voice"] or _default_voice()
    ref_audio = resolved["ref_audio_path"]
    if not ref_audio and voice:
        ref_audio = f"reference/{voice}.wav"

    prompt_text = resolved["prompt_text"] or voices.get(voice, "")

    # voice / ref_audio_path / prompt_text 由推导得出,覆盖 resolved 的同名项。
    # 必须先从 resolved 里摘掉再展开,否则 Settings(**resolved, **derived)
    # 会得到"同一个关键字传了两次"(Python 对重复 kwarg 是 TypeError,不是静默覆盖)。
    derived = {
        "voice": voice,
        "ref_audio_path": ref_audio,
        "prompt_text": prompt_text,
    }
    for k in derived:
        resolved.pop(k, None)

    return Settings(
        **resolved,
        **derived,
        voices=voices,
        config_sources=MappingProxyType(origins),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例(server/engine 都读它)。"""
    return build_settings()