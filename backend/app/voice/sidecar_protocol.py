"""sidecar 进程协议单源(零依赖):backend venv 与 CosyVoice venv 两边共用。

tts_sidecar.py 以脚本方式运行时,其所在目录自动在 sys.path[0],
直接 `from sidecar_protocol import ...` 即可;backend 侧走包导入。
"""

from __future__ import annotations

import re

SIDECAR_VERSION = 2
"""协议版本:sidecar /health 响应携带,backend 校验;不匹配=进程代码过期,拒绝静默复用。
v2:/tts_stream 分句流式端点取代 /tts 整段端点。"""

# ---- 分句(逐句合成压首包;规则已在 prototypes/tts-latency 实测定案) ----

_HARD_PUNCT = "。!?!?;\n"
# ASCII 逗号 / 全角逗号 / 顿号 / 全角冒号 / 全角分号 / ASCII 冒号
_SOFT_PUNCT = ",，、：；:"
_HANZI_RE = re.compile(r"[一-鿿]")


def _hanzi_len(s: str) -> int:
    return len(_HANZI_RE.findall(s))


def _hard_split(text: str) -> list[str]:
    """硬标点(。!?!?;\n)切段,标点保留在句尾;末尾无标点的尾段收进。"""
    chunks: list[str] = []
    buf: list[str] = []
    for ch in text:
        buf.append(ch)
        if ch in _HARD_PUNCT:
            chunks.append("".join(buf))
            buf = []
    tail = "".join(buf)
    if tail.strip():
        chunks.append(tail)
    return chunks


def _soft_split(chunk: str, max_len: int) -> list[str]:
    """超长段按软标点贪心切:在不超过 max_len 的最后一个软标点后切;
    无可用软标点则整段放行(交给 CosyVoice 模型内部分块兜底)。"""
    out: list[str] = []
    rest = chunk
    while _hanzi_len(rest) > max_len:
        cut = -1
        n = 0
        for i, ch in enumerate(rest):
            if _HANZI_RE.match(ch):
                n += 1
            if ch in _SOFT_PUNCT and n <= max_len:
                cut = i
        if cut < 0:
            break
        out.append(rest[: cut + 1])
        rest = rest[cut + 1 :]
    if rest.strip():
        out.append(rest)
    return out


def split_for_tts(text: str, max_len: int = 30) -> list[str]:
    """text → 分句列表(逐句合成压首包)。

    硬标点切句;首句遇软标点提前切(首包句尽量短);超 max_len 汉字的段软标点贪心再切。
    """
    out: list[str] = []
    for i, chunk in enumerate(_hard_split(text)):
        if i == 0:
            head_done = False
            for j, ch in enumerate(chunk[:-1]):
                if ch in _SOFT_PUNCT:
                    head, tail = chunk[: j + 1], chunk[j + 1 :]
                    if tail.strip():
                        out.append(head)
                        out.extend(_soft_split(tail, max_len))
                        head_done = True
                        break
            if not head_done:
                out.extend(_soft_split(chunk, max_len))
            continue
        if _hanzi_len(chunk) <= max_len:
            out.append(chunk)
        else:
            out.extend(_soft_split(chunk, max_len))
    return [s for s in out if s.strip()]
