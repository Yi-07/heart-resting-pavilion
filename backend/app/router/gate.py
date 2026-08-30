"""危机闸门(backend-plan §6;spec §4 L3 隔离:crisis/route 只走规则,确定性)。

词典+打分 = 实现细节(单源即本模块,与 L6 规则引擎共享的单一词典来源二期接线):
- 两档词典:核心词 = 自杀意念/自伤直接表述,权重 1.0;软信号词 = 低档位,
  权重 0.4(单独不足以致危机;软信号→risk 复核归 agents,步骤 4 接)
- severity = 命中词权重最大值(不累加,防多软词堆叠误伤)
- hit = severity ≥ config.CRISIS_GATE_THRESHOLD(默认 0.7)
- matched = 命中词列表(供审计 §9.4,不含原文本身)
- 词典为 MVP 最小占位(危机核心词先跑),内容运行时补
纯函数、无 IO、无状态;目标 ≤10ms/条;emotion_label 绝不进本模块。
"""

from dataclasses import dataclass, field

from app import config

CORE_TERMS: dict[str, float] = {
    "不想活": 1.0,
    "活不下去": 1.0,
    "想死": 1.0,
    "自杀": 1.0,
    "轻生": 1.0,
    "结束生命": 1.0,
    "了结自己": 1.0,
    "自残": 1.0,
    "伤害自己": 1.0,
}

SOFT_TERMS: dict[str, float] = {
    "绝望": 0.4,
    "没意义": 0.4,
    "想消失": 0.4,
    "解脱": 0.4,
    "撑不下去": 0.4,
}

_ALL_TERMS: dict[str, float] = {**CORE_TERMS, **SOFT_TERMS}


@dataclass(frozen=True)
class GateResult:
    hit: bool
    matched: list[str] = field(default_factory=list)
    severity: float = 0.0


def check(text: str) -> GateResult:
    """单条用户文本过闸;每条 user_input 必经,命中即危机(网关转危机序列+审计)。"""
    matched = [term for term in _ALL_TERMS if term in text]
    severity = max((_ALL_TERMS[term] for term in matched), default=0.0)
    return GateResult(
        hit=severity >= config.CRISIS_GATE_THRESHOLD,
        matched=matched,
        severity=severity,
    )
