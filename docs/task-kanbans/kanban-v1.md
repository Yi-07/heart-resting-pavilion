# 心栖阁 · 跨会话执行看板 kanban-v1

> **职能**:多对话窗口接力的共享执行清单——步骤执行状态单源;勾选=已完成并 commit。
> **优先级**:新会话开工必读顺序 = CLAUDE.md → 本文 → 同目录 `handoff.md`;步骤状态与本文冲突时以本文为准(优于任何会话记忆)。
> **单源边界**:构建顺序/验收判据/命令单源 = CLAUDE.md §4/§8,本文只记执行状态与分派,不复制判据;完成一步的前提=跑过 §8 对应用例并停下汇报获人确认。

## 0. 工作方式(本看板的执行模式)

- 主会话只做:决策、编码(Edit/Write)、commit、看板与交接快照更新、向人汇报。
- 高噪音步骤派子 agent(Agent 工具)黑盒执行,主会话只回收结论,不进中间输出:
  - 跑后端三件套/前端检查 → 回收「过/挂 + 失败摘要(文件:行)」
  - 浏览器 E2E 验证(playwright 对真实前后端) → 回收「验收判据逐条命中/未中」
  - 大文件蒸馏(如 preview mockup 结构) → 回收结构化要点
  - 全库检索/多文件摸底 → 回收结论 + 文件:行号
- 依据:单窗口实测,工具中间输出(测试日志/浏览器快照/检索面)会快速吃掉主上下文并污染推理现场。
- 汇报纪律不变:每步完成停下汇报 → 人确认 → commit(勾选+handoff 同步)→ 继续。

## 1. 构建顺序(CLAUDE.md §8;每步=前后端联动切片)

- [x] 步骤1 契约类型(schema+messages.ts)· `6c58aae`
- [x] 步骤2 WS 网关最小版+危机闸门 · `f226fbb`
- [x] 步骤3 answer(种子语料真检索) · `324bf0a`
- [x] 步骤4 collect 多轮采集(逻辑层先验) · `07cc917`
- [ ] 步骤5 黑板(SVG 渲染+视觉判据)← **当前**
- [ ] 步骤6 记忆(Redis 前置)
- [ ] 步骤7 Live2D
- [ ] 步骤8 语音(ASR+TTS)
- [ ] 步骤9 工具(station 懒生成·admin)

## 2. 当前步骤展开(完成后清空细节,§1 勾选即档)

### 步骤5 黑板 · 范围与分派

范围:board 模块(render/diff/registry/粉笔效果)· 模板声明 3 个 · state/round 状态机 · mood 选择器 · chat 面板+危机横幅 · audio 队列骨架 · App.vue 按 v7 舞台布局重组。接口签名单源 = frontend-plan §4/§5;视觉基准 = `architecture/preview/l1-ui-mockup-v7.html`(已蒸馏进 handoff §4,勿整读源文件)。

- [ ] `board/diff.ts` —— 纯函数:新增/变化/置 null 三态(测试接缝)
- [ ] `board/templateRegistry.ts` —— register/get;重复 id throw,未注册由 render 捕获
- [ ] `board/renderer.ts` —— render(未知模板记 WARN 跳帧不崩)+ 粉笔手绘(线中点抖动/椭圆半径噪声/dash-reveal/粉笔光标;feDisplacementMap 只套图形不套文字)
- [ ] 模板声明 3 个:beck_formulation 六字段 / emotion_wheel / stage_map(锚点与坐标参照 handoff §4 蒸馏)
- [ ] `state/round.ts` —— transition+RSEvent;非法迁移忽略记 DEBUG;持 emotionLabel(写序:first_frame → mood 本地 → 精稿,回合内手点不被精稿回退)
- [ ] `mood/selector.ts` —— 右上浮出/10s 超时回工具栏 pill/上报 mood_select
- [ ] chat —— 气泡+流式文本+危机横幅;点气泡展开抽屉,✕ 收起
- [ ] `audio/queue.ts` —— enqueue 顺序播/stopAndFade 淡出/onPlayback 广播(真音频帧步骤 8 到)
- [ ] App.vue 重组 v7 布局 —— 黑板左 64%+四角 HUD+呼吸光晕+zoom;工具栏/输入条;Live2D 与语音留位
- [ ] 测试四接缝:diff / render 未知模板 / transition 全迁移 / audio 队列顺序与抢占(frontend-plan §8)
- [ ] 验收:用例 2 前端判据(心情选择器、黑板粗稿→逐轮增量→精稿可见、总结+邀请语)+ 用例 3(热线横幅+stage_map、无心情选择器)—— 子 agent 驱动真实前后端逐条回报

## 3. 接力规程

1. 收尾窗口(达成交接点):更新本文勾选与 §2 → 重写 `handoff.md` 为最新现状 → 一并 commit → 告知人可开新窗。
2. 新窗口开工:读 CLAUDE.md → 本文 → handoff.md → 按本文 §0 工作方式继续当前步骤。
3. 任何窗口发现本文与代码实况不符:以代码+git 为准,当场修正本文(文档 bug 处理同 CLAUDE.md 冲突解决)。
