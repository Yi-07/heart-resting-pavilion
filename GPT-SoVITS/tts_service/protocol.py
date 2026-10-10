"""分句协议。

从 backend/app/voice/tts_service/protocol.py 复制(去掉 backend 包上下文依赖),
规则与那一份逐字一致:硬标点断句 → 首句优先在软标点切出更小的头块 → 软标点兜底。

复制而非 import 的原因:GPT-SoVITS 跑在自己的 conda 环境里,拿不到 backend 包。
两份若要改,必须同步改(SIDECAR_VERSION 语义上就是这件事的护栏)。
"""

from __future__ import annotations

import re

PROTOCOL_VERSION = 2
"""与 backend/app/voice/tts_service/protocol.py 的 SIDECAR_VERSION 对齐。"""

_HARD_PUNCT = "。!?!?;\n"
_SOFT_PUNCT = ",，、：；:"
_HANZI_RE = re.compile(r"[一-鿿]")

# 拉丁字母。GPT-SoVITS 的 g2p_en 依赖 nltk 的 cmudict,本机缺失该语料,
# 任何含 ASCII 字母的文本(含单个 "A")都会在 g2p 阶段抛 LookupError,
# 且首次触发要卡 12s 下载/查找。这里只做检测,判定放在 engine 的输入守卫里。
_ASCII_LETTER_RE = re.compile(r"[A-Za-z]")


def _hanzi_len(s: str) -> int:
    return len(_HANZI_RE.findall(s))


def has_ascii_letter(s: str) -> bool:
    """文本是否含 ASCII 英文字母(含单个字母)。"""
    return bool(_ASCII_LETTER_RE.search(s))


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
