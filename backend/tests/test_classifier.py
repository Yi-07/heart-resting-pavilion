"""classifier 接缝钉测试(spec §4 L3 分层判定):规则三级、LLM 模糊路径、兜底。"""

import asyncio

from app.llm import LLMError, Message
from app.router import classifier
from app.router.classifier import Classification, RouteLabel, classify


class _StubProvider:
    """chat_json 可编程 stub;不命中规则路径时才被调用"""

    def __init__(self, result: RouteLabel | None = None, error: Exception | None = None,
                 delay: float = 0.0) -> None:
        self.result = result
        self.error = error
        self.delay = delay
        self.calls = 0

    async def chat(self, messages: list[Message]) -> str:
        raise AssertionError("classify 规则路径不应调用 chat")

    async def stream(self, messages: list[Message]):
        raise AssertionError("classify 不用 stream")
        yield ""  # pragma: no cover

    async def chat_json(self, messages: list[Message], schema: type) -> object:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


# ---- 规则路径(不碰 LLM) ----


async def test_rule_knowledge_question():
    c = await classify("什么是正念", provider=_StubProvider())  # type: ignore[arg-type]
    assert c == Classification("answer", None, 0.9, True, "rule")


async def test_rule_distress_collect():
    c = await classify("最近很焦虑睡不着", provider=_StubProvider())  # type: ignore[arg-type]
    assert c.route == "collect"
    assert c.source == "rule"
    assert c.emotion_label == "焦虑"  # 快速研判标签随规则路径带出
    assert c.needs_rag is False


async def test_rule_greeting_answer_no_rag():
    c = await classify("你好呀", provider=_StubProvider())  # type: ignore[arg-type]
    assert c == Classification("answer", None, 0.9, False, "rule")


async def test_knowledge_beats_distress():
    # "如何缓解焦虑":知识问法优先于困扰信号
    c = await classify("如何缓解焦虑", provider=_StubProvider())  # type: ignore[arg-type]
    assert c.route == "answer"
    assert c.needs_rag is True


# ---- LLM 模糊路径 ----


async def test_llm_fuzzy_answer():
    stub = _StubProvider(RouteLabel(route="answer", emotion_label=None, confidence=0.85))
    c = await classify("帮我说说这事儿", provider=stub)  # type: ignore[arg-type]
    assert c.route == "answer"
    assert c.source == "llm"
    assert stub.calls == 1


async def test_llm_low_confidence_falls_back_to_collect():
    stub = _StubProvider(RouteLabel(route="answer", emotion_label=None, confidence=0.5))
    c = await classify("帮我说说这事儿", provider=stub)  # type: ignore[arg-type]
    assert c.route == "collect"  # conf<0.6 → collect 兜底(安全侧)
    assert c.source == "fallback"


async def test_llm_error_falls_back_to_collect():
    stub = _StubProvider(error=LLMError("网络断"))
    c = await classify("帮我说说这事儿", provider=stub)  # type: ignore[arg-type]
    assert c == Classification("collect", None, 0.0, False, "fallback")


async def test_llm_timeout_falls_back_to_collect():
    stub = _StubProvider(RouteLabel(route="answer", confidence=0.9), delay=0.2)
    c = await classify("帮我说说这事儿", provider=stub, timeout_s=0.05)  # type: ignore[arg-type]
    assert c.route == "collect"
    assert c.source == "fallback"


def test_quick_label_map():
    assert classifier.quick_label("我好累") == "疲惫"
    assert classifier.quick_label("随便聊聊") is None
