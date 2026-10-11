"""sidecar 进程协议(**legacy / deprecated**)。

CosyVoice 保留不删除,但已不是 active path:默认 TTS_MODE=remote 走
GPT-SoVITS 远程服务(9001)。本模块只服务 TTS_MODE=local 的 sidecar 进程。

**分句规则已迁出**:分句与"用哪个 TTS 实现"无关。住在 CosyVoice 的 sidecar
协议里,会让 active path(answer 路的句子泵)反过来依赖 legacy 模块,换引擎
就得改一遍分句,两处必然漂移。现在规则的 single source =
`app.voice.sentence_split`,本模块只保留 SIDECAR_VERSION 与再导出。

为什么保留再导出而不是删干净:`tts_sidecar.py` 以脚本方式运行,
其所在目录自动在 sys.path[0],它 `from sidecar_protocol import ...` 是刻意的
解耦方式;既有测试也走这个 import 路径。保留是为了路径稳定,不是"没迁完"。
新代码请直接 `from app.voice.sentence_split import SentenceSplitter, split_for_tts`。
"""

from __future__ import annotations

from app.voice.sentence_split import (  # noqa: F401 — 再导出,见模块文档
    DEFAULT_FIRST_SENTENCE_HANZI,
    DEFAULT_MAX_SENTENCE_HANZI,
    SentenceSplitter,
    split_for_tts,
)

SIDECAR_VERSION = 2
"""协议版本:sidecar /health 响应携带,backend 校验;不匹配=进程代码过期,拒绝静默复用。
v2:/tts_stream 分句流式端点取代 /tts 整段端点。"""