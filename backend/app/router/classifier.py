"""分层判定(spec §4 L3):规则先判明显 case → 模糊才调 LLM(复用规则引擎,零新增组件)。

- 规则三级(确定性,优先级从上到下):
  1. 知识问法命中 → answer,needs_rag=True
  2. 情绪困扰信号命中(第一人称近况/负面) → collect,顺带关键词快速研判标签
  3. 问候命中 → answer,needs_rag=False(直接生成)
- 其余模糊 → LLM 拿 {route, emotion_label, confidence};needs_rag 仍以知识问法
  词表判(RAG 门控复用同一分层判定,spec §4 L3)
- LLM conf < CLASSIFIER_LLM_MIN_CONF(0.6)→ 兜底 collect(collect 比 answer 安全:
  错了只是多问一句);LLM 失败/超时同样 collect 兜底
- 规则路径 conf = CLASSIFIER_RULE_CONF(0.9)
- 隔离约束:emotion_label 只随结果携带喂黑板/Live2D,绝不参与 route 判定
词表为 MVP 最小占位,内容运行时补。
"""

import asyncio
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app import config
from app.llm import LLMError, Message, get_provider
from app.llm.provider import OpenAICompatProvider

KNOWLEDGE_PATTERNS: tuple[str, ...] = (
    "什么是", "是什么", "为什么", "何为", "如何", "怎么", "怎样",
    "区别", "原理", "方法", "介绍", "有用吗", "有没有用", "怎么办", "哪个",
    "办法", "技巧", "建议", "缓解", "改善", "入睡", "帮助",
)
DISTRESS_SIGNALS: tuple[str, ...] = (
    "最近", "总是", "一直", "每天", "好累", "太累", "难受", "烦", "睡不着",
    "失眠", "压力大", "崩溃", "心情不好", "不开心", "emo", "焦虑", "紧张",
    "低落", "难过", "孤独", "委屈", "内耗",
)
GREETINGS: tuple[str, ...] = (
    "你好", "您好", "嗨", "哈喽", "早上好", "中午好", "下午好", "晚上好",
    "晚安", "在吗", "hi", "hello",
)
PURE_CONCEPT_PATTERNS: tuple[str, ...] = (
    "什么是", "是什么意思", "何为", "区别", "原理", "介绍一下", "科普",
)
"""纯概念问句(ADR-003 采集态门控):问"X 是什么"式概念,与用户具体场景无关。
求助性词(怎么办/建议/缓解)不在内——它们依赖场景,采集态中留 collect 轻回应。
词表为 MVP 最小占位,内容运行时补。"""

EXPLICIT_ASK_TERMS: tuple[str, ...] = (
    "你先回答", "先回答我", "你倒是", "直接回答", "我想知道", "你先告诉我",
)
"""用户明确要求先回答(ADR-003 短答升级):命中即允许短答支线,不必凑满两次追问。"""
QUICK_LABELS: dict[str, str] = {"焦虑": "焦虑", "紧张": "焦虑", "失眠": "疲惫", "累": "疲惫", "低落": "低落", "难过": "低落"}
"""快速研判第一级标签(粗稿用);两级标签第二级=分析阶段 LLM 复核"""


class RouteLabel(BaseModel):
    """LLM 分层判定输出 schema(chat_json 用)"""

    route: Literal["answer", "collect"]
    emotion_label: str | None = None
    confidence: float


@dataclass(frozen=True)
class Classification:
    route: Literal["answer", "collect"]
    emotion_label: str | None
    confidence: float
    needs_rag: bool
    source: Literal["rule", "llm", "fallback"]


def quick_label(text: str) -> str | None:
    for signal, label in QUICK_LABELS.items():
        if signal in text:
            return label
    return None


def is_pure_concept(text: str) -> bool:
    """纯概念问句判定(采集态门控用;ADR-003)。求助性词已在 KNOWLEDGE_PATTERNS
    命中但不算纯概念——"我该怎么办"依赖用户场景,采集态中不该切走。"""
    return _hit(PURE_CONCEPT_PATTERNS, text)


def is_explicit_ask(text: str) -> bool:
    """用户明确要求先回答(采集态短答升级;ADR-003)。"""
    return _hit(EXPLICIT_ASK_TERMS, text)


def _hit(patterns: tuple[str, ...], text: str) -> bool:
    return any(p in text for p in patterns)


_CLASSIFY_SYSTEM = (
    "你是心理陪伴应用的意图分类器。判断用户输入该走哪条路:\n"
    "- answer:知识提问/科普查询/日常问候,用户想要一个回答\n"
    "- collect:用户在表达情绪困扰或近况倾诉,需要被倾听和梳理\n"
    '只输出 JSON:{"route":"answer|collect","emotion_label":"情绪词或null",'
    '"confidence":0到1的小数}'
)


def classify_rules(text: str) -> Classification:
    """规则速判(零 LLM,保 first_frame ≤300ms);模糊输入按 collect+中性兜底
    (spec §4 L4:LLM 未返不等待)。LLM 精化 emotion_label 异步做,不撤回已发帧。"""
    knowledge = _hit(KNOWLEDGE_PATTERNS, text)
    if knowledge:
        return Classification("answer", quick_label(text), config.CLASSIFIER_RULE_CONF, True, "rule")
    if _hit(DISTRESS_SIGNALS, text):
        return Classification("collect", quick_label(text) or "低落", config.CLASSIFIER_RULE_CONF, False, "rule")
    if _hit(GREETINGS, text):
        return Classification("answer", None, config.CLASSIFIER_RULE_CONF, False, "rule")
    return Classification("collect", None, 0.0, False, "fallback")


async def classify(
    text: str,
    provider: OpenAICompatProvider | None = None,
    timeout_s: float | None = None,
) -> Classification:
    """分层判定全路径(规则→LLM);任何失败都落到 collect(安全侧),不向上抛。"""
    fast = classify_rules(text)
    if fast.source == "rule":
        return fast

    # 模糊 → LLM;不等待(超时/失败即 collect 兜底,spec §4 L4)
    prov = provider or get_provider()
    timeout = timeout_s if timeout_s is not None else config.LLM_CLASSIFY_TIMEOUT_S
    try:
        result = await asyncio.wait_for(
            prov.chat_json(
                [Message("system", _CLASSIFY_SYSTEM), Message("user", text)], RouteLabel
            ),
            timeout=timeout,
        )
    except (LLMError, asyncio.TimeoutError, ValueError):
        return Classification("collect", None, 0.0, False, "fallback")
    if result.confidence < config.CLASSIFIER_LLM_MIN_CONF:
        return Classification("collect", result.emotion_label, result.confidence, False, "fallback")
    knowledge = _hit(KNOWLEDGE_PATTERNS, text)
    return Classification(result.route, result.emotion_label, result.confidence, knowledge, "llm")
