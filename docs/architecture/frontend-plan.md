# 前端实施方案 · 技术原型

> **权威源**：`architecture-spec.md`（架构）· `ws-contract.md`（契约）
> **不管面**：机制与参数以 spec 为准，消息格式以 ws-contract 为准，本文件不复制。
> **目标**：技术原型前端——跑通三路路由的可视化（黑板深化 / 心情选择器 / Live2D / 聊天 / 语音）。

---

## 1. 技术栈

| 项 | 选型 |
|---|---|
| 框架 | Vue 3 + Vite + TypeScript |
| 黑板 | SVG + **自研渲染器**（不引第三方图形库）|
| Live2D | pixi-live2d-display 0.4.0（Cubism4；钉 pixi.js 6.5.10 配套）|
| 传输 | 原生 WebSocket（对接 `ws-contract.md`）|
| 状态 | Pinia |
| 日志 | console logger（彩色，仿后端 Loguru 风格）|

---

## 2. 模块职责表

> **文件真源为文件系统**：本表只记职责与接口；文件增删改不回本表，**职责变化才改行**；接口相关事实留表内，纯实现细节由代码实施时入该模块 docstring、同 commit 出表。

| 模块 | 职责与接口 |
|---|---|
| ws | 连接/重连/seq 校验/消息分发（connect/on/send）；messages 为 9 种消息类型定义（严格对齐 ws-contract）；契约对齐测试抽 ws-contract「数据对象」formulation 字段名与本地类型比对（§8）；session_id 经 localStorage 持久化（ADR-005） |
| board | `render(templateId,data,seq)` 通用渲染（读模板声明→增量绘制）·`diff(seq+新字段→动画)`·registry 为模板声明注册表（`register(decl)`/`get(templateId)`；测试模板 3 个，声明类型见 §5.1）；粉笔效果（抖动/dash-reveal/光标/滤镜）为实现细节，实施时入 docstring |
| mood | 今日心情选择器（浮出/超时/mood_select 上报） |
| l2d | pixi-live2d-display 封装+表情映射（版本钉子见「1. 技术栈」，不重复） |
| audio | 音频队列与播放：enqueue（chunk） 入队顺序播放 · stopAndFade（） 淡出当前声并清队（first_frame 抢占时调，时长见 §6）· onPlayback（cb） 广播播放状态；l2d 订阅播放事件驱动口型，播放不依赖立绘加载 |
| chat | 气泡+流式文本+危机横幅（ChatPanel）；输入单源文本：文字/麦克风（录音→/asr/transcribe 转写→追加回填文本框，用户确认发送，ADR-004）（input） |
| station | 心灵补给站：触发生成/等待态/md 预览/导出 |
| state | 回合状态机 `transition(event)`（§3）·持当前情绪 emotionLabel：写者按 first_frame.emotion_label → mood_select 本地写 → 精稿 draw.data.emotion.label 次序覆盖，本回合内用户手点不被精稿回退，first_frame 重置；Pinia store |
| logger | console 彩色 logger（INFO/WARN/ERROR） |

> **工具栏工具范围**：今日心情（即心情选择器，MVP，mood_select）· **心灵补给站（方案书入口，MVP：点击触发生成 + 等待态"正在为你整理" + md 预览 + 导出 md；pdf 导出属二期未实现，见 station.ts 注记）** · 心灵练习 / 留言墙——前端留入口 UI + TODO 占位（二期）· 设置——模型配置（MVP）+ 隐私 / 记忆治理（MVP，含用户删除权）+ 偏好 / 通知（二期 TODO）

> **UI 参考**：默认实现见 `preview/l1-ui-mockup-v7.html`。黑板左 64% 横向（细橡木+HUD+呼吸+粉笔手绘）· Live2D 叠右下 · 气泡头部旁；聊天抽屉点气泡展开；心情右上 10s；rail 磁吸右缘。**接口固定，视觉可替换。**
>
**UI 范式**：组件级范式见 `preview/l1-ui-taste.html`（已正式化进 `src/`），与 v7 **互为参考、互补**；同一组件可能两套 UI 显示并存。已裁定的组件规格（取自该文件）：

- 材质分层：面板为重玻璃，按钮/输入条为 tinted 轻玻璃（语义靠色调不靠厚度）；玻璃只用于悬浮层，不进内容层；尺寸/时长等数值以该文件为准，不复制到本文
- 工具栏：logo 为 heart-handshake 裸图标；route-tabs → 单状态 chip（图标+英文链路+灯点，三部分同步切换过渡，crisis 态转暖色）；工具按钮 hover 边缘流光（conic + `@property --ang`，注册见 main.css）+ 按压即缩
- 输入条：薄玻璃 + focus 光晕；发送钮为纸飞机圆钮，聚焦时从右缘「液芽分体」（goo 滤镜剪影只在动画瞬间显形，静止零重影），失焦收回；chip 无 answer 态——answer 无 first_frame 帧（ws-contract「3.1 first_frame」），与旧 route-tabs 同局限
- 设置/补给站面板：重玻璃浮层 + 分组卡 + 分段药丸（provider 选择）+ 高危确认层（文字与按钮居中）
- 图标为 Lucide 内联 SVG，不引 CDN 运行时；颜色变量唯一记录处见 main.css `:root`

**冲突裁定（护栏）**：两份参考对同一组件样式并存且本文未写明取舍时——**停下问人**，不自动择一。

> **交互模式（对齐 v7 观感）**：
> - 聊天抽屉：常态隐藏 → 点气泡展开 + 气泡隐身 → ✕ 收起还原
> - 心情选择器：右上浮出 · 6 标签 · 10s 超时回工具栏 pill（pill 可点击再开）
> - rail：磁吸右缘可拖 · 点击开时间线
> - 黑板：zoom 按钮全屏查看 · 粉笔逐帧绘制 + 光标跟随

> **插件化（二期）**：接口+注册表+配置拼装。`Live2DProvider{load,setExpression,setSpeaking,hit}` · `BoardTheme` · `ToolPlugin{id,title,icon,panel}` · registry 通用化。MVP 用默认实现。

---

## 3. 回合状态机

```
idle ──send user_input──▶ awaiting_first_frame
awaiting_first_frame ──first_frame──▶ collecting(清黑板/重置 seq 基线/浮心情选择器)
collecting ──draw(增量)──▶ collecting(继续)
collecting ──充分度达标(后端停采集)──▶ analysis(显示"收尾中")
analysis ──draw(精稿)+text_delta──▶ final
final ──done──▶ idle
任意状态 ──error──▶ idle(温和兜底)
任意状态 ──新 first_frame──▶ collecting(新回合抢占,清黑板)
```

- **心情选择器**：collecting 开始时浮出，10s 超时自动收起；crisis 不浮
- **crisis**：first_frame（route=crisis）→ 显示热线横幅 + 支持性画面（stage_map）
- **analysis**：最后回答提交 → 精稿 draw 之间，前端显示"收尾中"（纯前端推断，无专用消息）

---

## 4. 模块接口（关键签名）

```ts
// ws/client.ts
connect(): Promise<void>                 // 拒绝时抛 WSError;断线重连内部处理,带原 session_id
on(type: WSMsgType, handler: (msg: WSMsg) => void): () => void
                                         // 返回退订函数,组件卸载时摘钩子
send(msg: CSMsg): void                   // user_input / mood_select;未连接时抛错,UI 以等待态禁用输入保证不触
// seq 校验单点在此:丢弃 seq≤已处理 的旧帧,下游收到即新帧

// board/renderer.ts
class BoardRenderer {                    // export 类;实例由 BoardCanvas.vue 持有,渲染入口在组件内
  render(templateId: string, data: TemplateData): void
}
// TemplateData = Formulation | EmotionWheelData | StageMapData(契约 §5.1 三型)
// 未知 templateId:记 WARN 跳过本帧,黑板不崩

// board/diff.ts
diff(prev: TemplateData, next: TemplateData): string[]
// 按声明字段比对新旧,返回新增/变化的字段(值变化也算);纯函数

// board/templateRegistry.ts
register(decl: TemplateDecl): void       // 重复 id 直接 throw(开发期错误)
get(templateId: string): TemplateDecl    // 未注册 throw,由 render 捕获

// audio/queue.ts
enqueue(chunk: AudioChunk): void         // 入队顺序播放,格式随 chunk.format
stopAndFade(): void                      // 抢占淡出,时长见 §6
onPlayback(cb: (active: boolean) => void): void   // l2d 订阅驱动口型

// mood/selector.ts
show(): void   hide(): void
onSelect(mood: MoodKey): void            // send mood_select,并写 state.emotionLabel

// l2d/live2d.ts
setExpression(emotionLabel: string): void   // watch state.emotionLabel 驱动;未知标签落到中性兜底表情
setSpeaking(active: boolean): void          // 由 audio 播放事件驱动口型;模型未加载时 no-op 记 WARN

// state/round.ts
transition(event: RSEvent): void
// RSEvent = { kind: "user_sent" } | { kind: "frame", msg: S2CMsg }
// 非法迁移(如 idle 收 draw):忽略并记 DEBUG 日志,不崩
```

---

## 5. 关键难点骨架

### 5.1 模板声明类型（TS）

```ts
type Widget = "text" | "highlight" | "rough_ellipse+text" | "rough_box+text" | "wheel_mini";

interface FieldDecl {
  key: string;                 // 数据字段名,须与该模板 TemplateData 字段一致(beck=Formulation 六键)
  anchor: string;              // "asset#root" | 无素材时的相对坐标 "zone:top"
  widget: Widget;
  emptyIfNull?: boolean;       // 数据为 null 时不画该格
}

interface TemplateDecl {
  id: string;
  asset?: { src: string; zone: string };   // 静态素材层;无 → 纯几何
  fields: FieldDecl[];
}
```

### 5.2 渲染器 diff 伪码

```
function render(templateId, data):         # 新鲜度由 ws 层保证(§4),收到即新帧
  decl = registry.get(templateId)
  changed = diff(lastData, data)           # 新填/变化的字段
  for key in changed:
    if data[key] == null: continue         # 留白格不画
    widget = decl.field(key).widget
    draw(widget, data[key])                # 动画补画 + chalk 光标跟随
  lastData = data
```

### 5.3 回合状态机伪码

```
on WS message m:
  switch m.type:
    first_frame: audio.stopAndFade(); round.reset(); round.enter("collecting")
                 if m.route == "crisis": showHotline()   # stage_map 由后续 draw 帧渲染
                 else: mood.show(); board.render(m.template, 粗稿数据)
    draw:        board.render(m.template, m.data)
    text_delta:  chat.append(m.text); if m.final: chat.finalize()
    audio_chunk: audio.enqueue(m)
    done:        round.enter("idle"); mood.hide()
    error:       round.enter("idle"); chat.append(温和兜底话术)
```

---

## 6. WS 消息 → 前端行为

| 消息 | 前端行为 |
|---|---|
| first_frame | 回合重置；淡出停播当前音频（~100ms）；crisis→热线+stage_map；collect→心情选择器+粗稿 |
| draw | 渲染器增量画（按 seq）|
| text_delta | 气泡流式追加 |
| audio_chunk | 入队顺序播放；口型由播放事件驱动（抢占随 first_frame 淡出） |
| done | 收尾：收起等待态 |
| error | 温和兜底，回 idle |
| user_input（发）| 触发新回合 |
| mood_select（发）| 上报心情 |

---

## 7. 验收（前端视角，3 用例）

1. **answer**：输入"什么是正念" → 无黑板，气泡流式文本，结束
2. **collect**：输入"最近很焦虑睡不着" → 第一帧 → 心情选择器（10s 超时回退）→ 黑板粗稿 → 逐轮增量 → 精稿补全 → 分析总结+心灵补给站邀请语（方案书点击补给站触发生成）
3. **crisis**：输入"我不想活了" → 热线横幅 + stage_map，不弹心情选择器

---

## 8. 测试

- **框架与布局**：vitest（脚手架自带）；测试与模块同目录放 `__tests__/`，一接缝一文件
- **接缝钉测试**（只钉接缝，不测内部）：diff 新增/变化/置 null · render 未知模板跳帧不崩 · transition 状态机全迁移+非法迁移忽略 · audio 队列顺序与抢占淡出 · 契约对齐测试抽 ws-contract「数据对象」formulation 字段名与 messages.ts 比对，防两端漂移
- **分步冒烟**：构建顺序每步完成即跑对应用例（用例定义见 [acceptance-v1.md](../tests/acceptance-v1.md)「三链路验收」，前端判据见「7. 验收（前端视角，3 用例）」），不全套重跑
