"""TTS Service 协议:分句逻辑。

从 sidecar_protocol.py 复制,保持 SIDECAR_VERSION 同步。
独立部署时不需要 backend 包上下文。
"""

from __future__ import annotations

import re

SIDECAR_VERSION = 2
"""协议版本:与 sidecar_protocol.py 保持一致。"""

# ---- 分句(逐句合成压首包;规则已在 prototypes/tts-latency 实测定案) ----

_HARD_PUNCT = "。!?!?;\n"
_SOFT_PUNCT = ",，、：；:"
_HANZI_RE = re.compile(r"[一-鿿]")


def _hanzi_len(s: str) -> int:
    return len(_HANZI_RE.findall(s))


def _hard_split(text: str) -> list[str]:
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
    """text → 分句列表(逐句合成压首包)。"""
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
