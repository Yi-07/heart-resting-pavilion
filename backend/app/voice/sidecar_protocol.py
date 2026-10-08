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


# ---- 流式切句(句子泵用) ----
#
# split_for_tts 是批量的:拿到全文才能切。LLM 逐字出字,若等全文再切,
# 首句音频要等整段生成完 —— 那就退化成非流式了。
# SentenceSplitter 是它的流式对应物,只依赖"硬标点收尾"这条可增量判定的规则;
# split_for_tts 首句的"最小头块"技巧要向后看,流式下拿不到,故不复刻
# (延迟优先:宁可首句长一点,也不要等全文)。
#
# 只加在 backend 一侧 —— 服务端收到的是已切好的句子,不参与这段逻辑。
# 与 GPT-SoVITS/tts_service/protocol.py 需保持一致的是**分句规则本身**
# (_HARD_PUNCT / _SOFT_PUNCT / _hanzi_len);新增的流式类不参与同步。

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
