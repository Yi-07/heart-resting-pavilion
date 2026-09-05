"""计划制定者(spec §4 L5):基于完整 formulation 生成心灵补给站方案书(md)。

- 知识来源= RAG 检索条目进 prompt(方案基于知识不凭空编;检索失败 refs 空→通用建议)
- 安全边界(硬):非医疗声明必附(LLM 稿缺失则强制补,降级模板自带);
  危机回合不产素材(网关危机序列不写 station:input,天然绕过)
- 降级:LLM 失败/超时 → 确定性模板(字段填充);本函数**永不抛**,保证 latest 终态 ready
"""

from __future__ import annotations

import asyncio

from app import logger as app_logger
from app.llm import LLMError, Message, get_provider
from app.schema import Formulation

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="planner")

PLANNER_TIMEOUT_S = 90.0
"""方案书单次 LLM 上限(后台任务,不受 user_input 60s 预算约束;超时降级模板)"""

DISCLAIMER = (
    "> 本方案由心栖阁基于心理科普知识整理,不构成医疗诊断或治疗建议;"
    "如果困扰持续或加重,请及时寻求专业帮助。"
)

# ---- 降级模板练习库(按研判标签选;风格同 router/phrases) ----

PRACTICE_BY_LABEL: dict[str, list[str]] = {
    "焦虑": [
        "4-7-8 呼吸:吸气 4 秒、屏住 7 秒、呼气 8 秒,重复四轮,让身体先慢下来。",
        "给焦虑命名:写下「我在担心什么」,区分「我能做的」和「我控制不了的」。",
        "睡前一小时把烦心事写在纸上,合上本子,告诉自己明天再处理。",
    ],
    "低落": [
        "每天做一件小小的、曾经让你有成就感的事,哪怕只是整理桌面。",
        "出门走十分钟,不求目的地,让光照和移动帮一点忙。",
        "给一位你觉得安全的人发一条消息,不用长,说说今天就好。",
    ],
    "疲惫": [
        "允许自己休息:今天只完成必须做的事,其余的留给明天的自己。",
        "做一次「精力盘点」:列出最近消耗你的三件事,看看哪件可以暂缓。",
        "睡前放下屏幕,用十分钟拉伸或热水澡过渡到休息。",
    ],
}
PRACTICE_DEFAULT = [
    "正念呼吸三分钟:注意力放在呼吸上,走神了就轻轻带回,不评判。",
    "情绪日记:每天用一句话记下「今天的感受和原因」,一周后回看规律。",
    "给自己安排一段不被打扰的休息时间,像对待重要的约会一样守住它。",
]

_SYSTEM = (
    "你是心理科普工具「心栖阁」的方案书撰写者。根据用户的认知梳理(formulation)"
    "与对话小结,写一份温和、可执行的心理成长方案书。要求:"
    "1)输出 Markdown,一级标题「# 心理成长方案」;"
    "2)建议分 3-4 个小节(如:这次的梳理/可以试试的小练习/小提示),每条给具体做法,语气温暖不评判;"
    "3)只依据参考资料与梳理内容给建议,不编造心理学结论,不给诊断或用药意见;"
    "4)结尾单独一行引用块:本方案由心栖阁基于心理科普知识整理,不构成医疗诊断或治疗建议;"
    "如果困扰持续或加重,请及时寻求专业帮助。"
)


def _material_lines(f: Formulation, summary: str) -> list[str]:
    lines: list[str] = []
    if f.situation:
        lines.append(f"- 情境:{f.situation}")
    if f.emotion.label:
        strength = (
            f"(强度约 {round(f.emotion.intensity * 10)}/10)" if f.emotion.intensity is not None else ""
        )
        lines.append(f"- 情绪:{f.emotion.label}{strength}")
    if f.thought:
        lines.append(f"- 念头:{f.thought}")
    if f.behavior:
        lines.append(f"- 应对:{f.behavior}")
    if summary:
        lines.append(f"- 小结:{summary[:120]}")
    if not lines:
        lines.append("- (本次素材较少,从通用建议开始)")
    return lines


def _query(f: Formulation, summary: str) -> str:
    parts = [f.emotion.label, f.situation, f.thought, summary[:60]]
    joined = " ".join(p for p in parts if p)
    return joined or "情绪调节"


def _retrieve_refs(query: str) -> list[str]:
    try:
        from app.rag import get_engine  # 重依赖,函数内懒加载(既定模式)

        return [f"- 问:{r.question}\n  答:{r.answer}" for r in get_engine().retrieve(query)]
    except Exception as exc:  # noqa: BLE001 — RAG 失败降级:refs 空走通用建议
        logger.warning("degraded", layer="planner_rag", reason=str(exc)[:120])
        return []


def _messages(f: Formulation, summary: str, refs: list[str]) -> list[Message]:
    material = "\n".join(_material_lines(f, summary))
    refs_text = "\n".join(refs) if refs else "(无检索结果,请只给通用温和建议)"
    user = (
        f"## 梳理内容\n{material}\n\n## 参考资料(心理科普知识库检索)\n{refs_text}\n\n"
        "请为这位用户撰写方案书。"
    )
    return [Message(role="system", content=_SYSTEM), Message(role="user", content=user)]


def _with_disclaimer(md: str) -> str:
    """安全边界硬保证:LLM 稿没有声明行则强制补上。"""

    return md if "不构成" in md else f"{md}\n\n{DISCLAIMER}"


def _fallback(f: Formulation, summary: str) -> str:
    practices = PRACTICE_BY_LABEL.get(f.emotion.label or "", PRACTICE_DEFAULT)
    lines = [
        "# 心理成长方案",
        "",
        "## 这次的梳理",
        *_material_lines(f, summary),
        "",
        "## 可以试试的小练习",
        *[f"{i}. {p}" for i, p in enumerate(practices, 1)],
        "",
        "## 小提示",
        "一次只试一件,小小的一步也算数;感觉不合适就换下一件。",
        "",
        DISCLAIMER,
    ]
    return "\n".join(lines)


async def generate_report(f: Formulation, summary: str) -> str:
    """产方案书 md;任何失败路径都落降级模板,永不抛(调用方=后台任务)。"""

    refs = _retrieve_refs(_query(f, summary))
    try:
        provider = get_provider()
        md = await asyncio.wait_for(provider.chat(_messages(f, summary, refs)), PLANNER_TIMEOUT_S)
        md = md.strip()
        if md:
            logger.info("planner_llm_ok", refs=len(refs), length=len(md))
            return _with_disclaimer(md)
        logger.warning("degraded", layer="planner_llm", reason="empty_output")
    except LLMError as exc:
        logger.warning("degraded", layer="planner_llm", reason=str(exc)[:120])
    except asyncio.TimeoutError:
        logger.warning("degraded", layer="planner_llm", reason=f"timeout>{PLANNER_TIMEOUT_S:.0f}s")
    except Exception as exc:  # noqa: BLE001 — 后台任务兜底:保证 latest 终态 ready
        logger.warning("degraded", layer="planner", reason=str(exc)[:120])
    return _fallback(f, summary)
