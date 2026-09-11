"""契约字面量类型(ws-contract §5.2 枚举 + §3.6/§4.1 取值)。

与 frontend/src/ws/messages.ts 同名类型一一对应;改取值先改 ws-contract。
"""

from typing import Literal

Route = Literal["answer", "collect", "crisis"]
"""路由三值;first_frame 只取 collect|crisis(answer 型不发首帧,§3.1)"""

TemplateId = Literal["beck_formulation", "emotion_wheel", "stage_map"]
"""模板 id;beck=MVP 采集默认,wheel/stage_map=测试模板"""

MoodKey = Literal["难过", "低落", "平静", "还好", "开心", "很好"]
"""心情六档(§4.2)"""

ErrorCode = Literal["invalid_message", "timeout", "server_error"]
"""error 帧 code(§3.6)"""
