"""契约字面量类型(ws-contract §5.2 枚举 + §3.6/§4.1 取值)。

与 frontend/src/ws/messages.ts 同名类型一一对应;改取值先改 ws-contract。
"""

from typing import Literal

Route = Literal["answer", "collect", "crisis"]
"""路由三值;first_frame 三路统一下发(采集期打岔不发,§3.1/§6.1)"""

TemplateId = Literal[
    "beck_formulation", "emotion_wheel", "stage_map",
    "scene_default", "scene_focus", "scene_answer", "scene_crisis",
]
"""模板 id;beck 从 collect 链路退役枚举保留作几何测试模板,wheel/stage_map=测试模板,
scene_*=黑板场景化板式(blackboard-v1),scene_default 兼 collect 开场(§5.2)"""

MoodKey = Literal["难过", "低落", "平静", "还好", "开心", "很好"]
"""心情六档(§4.2)"""

ErrorCode = Literal["invalid_message", "timeout", "server_error", "ask_llm_failed"]
"""error 帧 code(§3.8);ask_llm_failed=问话 LLM 失败,采集态挂起待重试"""
