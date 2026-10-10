"""分句规则单源(backend 侧;零依赖、纯文本)。

为什么从 sidecar_protocol.py 里独立出来:
    分句是 **backend 与 TTS 服务共用的规则**,与"用哪个 TTS 实现"无关。
    之前它住在 sidecar_protocol.py 里,于是 CosyVoice 一标记 legacy,分句规则
    就跟着变成了"legacy 的东西" —— 但 answer 路的句子泵(active path)每天都在用
    它。规则必须独立于引擎实现存在,否则换引擎就得改一遍分句,两处必然漂移。

两套切法,用途不同(不要合并):
    split_for_tts    批量:拿到全文才能切。TTS 服务端逐句合成时用它。
    SentenceSplitter 增量:喂一段吐一句。句子泵用(LLM 逐字出字,等全文就丢流式)。
    SentenceSplitter 不复刻 split_for_tts 的"首句最小头块"技巧:那要向后看,
    流式下拿不到。延迟优先(宁可首句长一点,也不要等全文)。

与 GPT-SoVITS/tts_service/protocol.py 的同步义务:
    分句**规则**(_HARD_PUNCT / _SOFT_PUNCT / _hanzi_len / split_for_tts)
    两份必须逐字一致。TTS 服务跑在自己的 conda 环境里拿不到 backend 包,
    那份是复制而非 import —— 所以改动要同步改两处。
    SentenceSplitter 是 backend 独有的,服务端不参与这段逻辑,无需同步。
"""

from __future__ import annotations

import re

DEFAULT_MAX_SENTENCE_HANZI = 30
"""缓冲里超过这个汉字数还没遇到硬标点就强制切一刀(LLM 长时间不吐标点的兜底)。"""

DEFAULT_FIRST_SENTENCE_HANZI = 12
"""首句专用上限。

为什么单独限首句:流水线 TTFB ≈ 首句字数 × LLM 每字耗时 + 服务侧首块耗时。
首句越长,用户按下回车到第一句话出声的等待越久(实测 4 字 0.72s / 24 字 3.14s /
31 字 4.29s)。而且长首句还会挤掉交错的机会 —— 音频合成比不过文字剩余出字时间,
文字先出完,音频才到,就不交错。

只限首句、不动后续句子:一句话的引导语短一点语气略碎,代价可控;
把所有句子都切到 12 字则整段语气都碎,不值。
"""

_HARD_PUNCT = "。!?!?;\n"
# ASCII 逗号 / 全角逗号 / 顿号 / 全角冒号 / 全角分号 / ASCII 冒号
_SOFT_PUNCT = ",，、：；:"
_HANZI_RE = re.compile(r"[一-鿿]")


def _hanzi_len(s: str) -> int:
    return len(_HANZI_RE.findall(s))


# ---- 批量切分(服务端逐句合成用)----


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
    无可用软标点则整段放行(交给模型内部分块兜底)。"""
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


def split_for_tts(text: str, max_len: int = DEFAULT_MAX_SENTENCE_HANZI) -> list[str]:
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


# ---- 增量切分(句子泵用)----


class SentenceSplitter:
    """增量切句:喂进来的字符一旦能判定成完整句子就立刻吐出来。

    典型用法(句子泵):
        splitter = SentenceSplitter()
        for piece in llm_stream:
            for sentence in splitter.feed(piece):
                await synth(sentence)
        for sentence in splitter.flush():
            await synth(sentence)
    """

    def __init__(
        self,
        max_hanzi: int = DEFAULT_MAX_SENTENCE_HANZI,
        first_max_hanzi: int = DEFAULT_FIRST_SENTENCE_HANZI,
    ) -> None:
        self._buf = ""
        self._max_hanzi = max_hanzi
        self._first_max_hanzi = min(first_max_hanzi, max_hanzi)
        self._emitted = 0

    @property
    def pending(self) -> str:
        """缓冲区里还没凑成句的部分(诊断用)。"""
        return self._buf

    def _cap(self) -> int:
        """当前生效的字数上限:首句用短的,之后用常规的。"""
        return self._first_max_hanzi if self._emitted == 0 else self._max_hanzi

    def feed(self, piece: str) -> list[str]:
        """喂一段增量文本,返回本次新凑成的句子。"""
        self._buf += piece
        return self._drain(flush=False)

    def flush(self) -> list[str]:
        """回合收尾:把缓冲区剩下的内容作为最后一句吐出。"""
        return self._drain(flush=True)

    def _drain(self, *, flush: bool) -> list[str]:
        out: list[str] = []
        cap = self._cap()
        while self._buf:
            cut = self._next_hard_punct()
            if cut < 0:
                # 没有硬标点:缓冲超过上限就切(优先切在软标点之后,退而求其次按字数)
                if not flush and _hanzi_len(self._buf) <= cap:
                    break
                cut = self._next_soft_punct_or_len(cap)
                if cut < 0:
                    if not flush:
                        break
                    cut = len(self._buf) - 1
            sentence = self._buf[: cut + 1]
            self._buf = self._buf[cut + 1 :]
            if sentence.strip():
                out.append(sentence)
                self._emitted += 1
                cap = self._cap()
        return out

    def _next_hard_punct(self) -> int:
        for i, ch in enumerate(self._buf):
            if ch in _HARD_PUNCT:
                return i
        return -1

    def _next_soft_punct_or_len(self, cap: int) -> int:
        """超长兜底:在不超过 cap 的范围内找**最后一个**软标点切,找不到就按字数硬切。

        注意切点是在汉字数达到上限**之前**的那个标点,而不是之后 ——
        否则会切出 cap+1 汉字的块,违反自己声明的上限。
        """
        n = 0
        best = -1
        for i, ch in enumerate(self._buf):
            if n >= cap:
                break
            if ch in _SOFT_PUNCT:
                best = i
            if _HANZI_RE.match(ch):
                n += 1
        if best >= 0:
            return best
        # 没有软标点:按汉字数硬切到上限
        n = 0
        for i, ch in enumerate(self._buf):
            if _HANZI_RE.match(ch):
                n += 1
                if n > cap:
                    return i - 1 if i > 0 else -1
        return -1