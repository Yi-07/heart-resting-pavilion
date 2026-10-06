# 代码规范

> **职能**：跨文件的代码写法约定与性能约束单源，AGENTS.md「按任务先读·改码」指向此文档。约束所有或多个模块的写法（类型、结构、错误处理、性能）；单文件内部的实现细节以代码现状为准，不在此过多叙述。
> **何时改**：跨模块写法约定变化时同步本文。
> **术语**：深模块/浅模块网/接缝等术语定义见 [CONTEXT.md](../architecture/CONTEXT.md)「架构方法」。

## 类型

- 前端 TS 与后端 Pydantic 的类型对齐 [ws-contract](../architecture/ws-contract.md)；类型只定义一份，复用。
- TS 永不 `any`；不用 `Record<string, unknown>` 逃逸。
- Python 全量类型标注；入参出参过 Pydantic 校验。
- 契约字面量用模块级 Literal 别名（`app/schema/literals.py`），与前端 `messages.ts` 同名一一对应；内部枚举用 `str, Enum`，传参必须用成员，禁裸字符串。

## 命名

- Pydantic 模型用裸域名（`GateResult`、`Turn`、`FirstFrame`），不加 Schema 后缀。
- LLM 结构化输出的 schema 类用下划线前缀私有（`_ExtractOut` 式），不跨模块复用。
- 前后端契约类型单源在 [ws-contract](../architecture/ws-contract.md)，前端集中在 `src/ws/messages.ts`，后端集中在 `app/schema/`；模块局部类型放模块内。
- 后端包按「一个职能一个深模块目录」组织，`__init__.py` 经 `__all__` 再导出；目录风格细则见 [deep-module.md](deep-module.md) 与 [backend-plan](../architecture/backend-plan.md)「模块职责表」。

## 结构

- 函数式优先：纯函数、不可变数据；复杂操作拆具名辅助函数。
- 不可变数据的落点：值对象、结果、图出口事件用 frozen dataclass（`GateResult`、`Turn`、`Message` 式）；`CollectState` 是唯一可变黑板（图节点读写、网关持有）。
- 深模块：新模块设计与重构按 [deep-module.md](deep-module.md) 判据执行，新模块开工必读。
- 重依赖（chroma、sentence-transformers、语音模型、LangGraph、pixi.js）函数内懒加载，不在模块顶部 import；类型标注走 `TYPE_CHECKING`，预热路径同样函数内 import。

## 错误与日志

- WS 错误统一收口 error 帧：收口点在网关主 try/except（任何异常 error 帧加兜底话术，不崩连接），handler 内不散落 try/except。
- 子系统异常每模块一个 `XxxError`，docstring 写明调用方降级语义（不杀连接、不杀回合）。
- 异常被吞、功能降级处，统一记 `<域>_degraded` WARN 事件，带 reason/layer 字段。
- 广捕获（`except Exception`）必带行内理由注释：`# noqa: BLE001 — <降级理由>`。
- 日志用统一 logger，不直接调 print/标准 logging。获取方式：模块级 `logger = app_logger.logger.bind(service=SERVICE, module="<名>")`；连接级日志经 `Connection.log()` 补 session_id。
- 事件名即消息本体（snake_case 过去式，如 `first_frame_sent`、`crisis_gate_hit`），业务字段走 bind kwargs，不内嵌 message。
- 用户文本日志只经 `text_fingerprint()`（记长度与哈希前 8 位），永不落原文。
- 前端 fetch 不向调用方抛异常：模块内局部 helper 返回状态或 null，降级为 UI 状态。

## 性能热点

- 黑板渲染按字段 diff，不做整树重建；动画按 seq 增量。
- WS 消息批量/采样，不逐字转发，避免消息风暴。
- RAG/LLM 动态门控：普通/简单问题不走 RAG，知识查询才检索；预置问题库优先于 LLM 生成。
- 事件循环内禁同步重活：重活走 `to_thread` 或后台预热；机制依据见 [ADR-003](../adr/003-in-round-gating-and-loop-hygiene.md)。
- seq 发号纪律：仅 `draw`/`text_delta`/`audio_chunk`/`done` 盖章，`first_frame`/`error`/`replay` 不带且不消耗；seq 会话内全局递增，不随回合重置。

## 测试

- 后端单测平铺在 `tests/`，`test_<模块名>.py` 镜像 app 结构；pytest `asyncio_mode=auto`，异步测试不写 `@pytest.mark.asyncio`。
- 真 WS 链路回归放 `tests/e2e/` 独立脚本：`e2e_*.py` 直接 `python` 运行、不经 pytest 收集、依赖真服务在跑；共享客户端与帧时间线在 `e2e_lib.py`。
- 前端测试与源码同域：`__tests__/<名>.spec.ts`，vitest+jsdom；被测模块导出 `resetXxxForTest()` 供夹具复位。
- 契约改动必须同步两侧契约对齐测试：后端 `test_contract_alignment.py` 与前端 `contract-alignment.spec.ts` 均从 ws-contract 抽字段比对。
- 测试桩集中 `conftest.py` autouse（假记忆、语音静音、RAG 旗标）；测真实现时在模块导入期捕获原函数，fixture 内还原——运行期现取会拿到已打桩的假货。
- 测试钉在公开接口上（断言可观察结果，不窥内部状态），判据细则见 [deep-module.md](deep-module.md)「测试面」。

## Gotchas

- `--reload` 热重载开发必须配 `TTS_SIDECAR_KILL_ON_EXIT=0`：热重载重启后端进程时，退出钩子会连同杀掉 TTS sidecar；sidecar 一停，CosyVoice 模型要重新加载（分钟级）。设 0 后退出不杀 sidecar，模型常驻。
- sidecar 版本握手：协议单源在 `sidecar_protocol.py`，`SIDECAR_VERSION` 不匹配时拒绝复用，拒绝静默沿用旧进程。
- 模型缓存路径（HF_HOME/MODELSCOPE_CACHE）必须指向 ASCII 路径，中文用户名会让 sentencepiece 打不开文件。
- Windows 下 Python 脚本的 stdin/stdout 显式 UTF-8（GBK 陷阱）：e2e 脚本头 reconfigure，脚本内中文输出防 UnicodeEncodeError。
- 端口约定：后端 8000、TTS sidecar 9880、前端 dev 5173；9880 被占提示旧版 sidecar 残留。
