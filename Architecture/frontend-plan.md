# 前端实施方案 · 技术原型

> **权威源**:`architecture-spec-v3.md`(架构)· `ws-contract.md`(契约)
> **目标**:技术原型前端——跑通三路路由的可视化(黑板深化 / 心情选择器 / Live2D / 聊天 / 语音)。

---

## 1. 技术栈

| 项 | 选型 |
|---|---|
| 框架 | Vue 3 + Vite + TypeScript |
| 黑板 | SVG + **自研渲染器**(不引第三方图形库)|
| Live2D | pixi-live2d-display 0.4.0(Cubism4;钉 **pixi.js 6.5.10** 配套——stable 0.4.0 peer 仅 pixi ^6,0.5.0-beta 配 pixi 7,均不兼容现行 pixi 8.20.0,2026-08-22 核实)|
| 传输 | 原生 WebSocket(对接 `ws-contract.md`)|
| 状态 | Pinia |
| 日志 | 轻量 console logger(彩色,仿后端 Loguru 风格)|

---

## 2. 目录结构

```
src/
  main.ts  App.vue
  logger.ts                  # console 彩色 logger(INFO/WARN/ERROR)
  ws/
    client.ts                # WS 连接 / 重连 / seq 校验 / 消息分发
    messages.ts              # 8 种消息类型定义(严格对齐 ws-contract)
  board/
    renderer.ts              # 通用渲染器:读模板声明 → 增量绘制
    diff.ts                  # 字段 diff(seq + 新字段 → 动画)
    chalk.ts                 # 粉笔效果:抖动 / dash-reveal / 光标 / 滤镜
    templateRegistry.ts      # 模板声明注册表
    templates/
      emotion_wheel.ts       # 测试模板 1
      beck_formulation.ts    # 测试模板 2(默认)
      stage_map.ts           # 测试模板 3
  mood/
    selector.ts              # 今日心情选择器(浮出/超时/mood_select 上报)
  l2d/
    live2d.ts                # pixi-live2d-display 0.4.0 封装(pixi.js 钉 6.5.10)+ 表情映射
  chat/
    ChatPanel.vue            # 气泡 + 流式文本 + 危机横幅
    input.ts                 # 文字/麦克风输入(录音→上传 ASR)
  station/
    StationPanel.vue         # 心灵补给站:触发生成/等待态/md 预览/导出
  state/
    round.ts                 # 回合状态机
    store.ts                 # Pinia store
```

> **工具栏工具范围**：今日心情（=心情选择器，MVP，mood_select）· **心灵补给站（方案书入口，MVP：点击触发生成 + 等待态"正在为你整理" + md 预览 + 导出 md/pdf，REST 通道，research-v1 Q3）** · 心灵练习 / 留言墙——**前端留入口 UI + TODO 占位**（不实现逻辑，二期）· 设置——模型配置（MVP，R3）+ 隐私 / 记忆治理（MVP，V2.8，**用户删除权 = 2026-07-15 施行《AI 拟人化互动服务管理暂行办法》合规义务，确认保留**）+ 偏好 / 通知（二期 TODO）

> **UI 参考**：默认实现 = `preview/l1-ui-mockup-v7.html`。黑板左 64% 横向（细橡木+HUD+呼吸+粉笔手绘）· Live2D 叠右下 · 气泡头部旁；聊天抽屉点气泡展开；心情右上 10s；rail 磁吸右缘。**接口固定，视觉可替换。**

> **交互模式（对齐 v7 观感）**：
> - 聊天抽屉：常态隐藏 → 点气泡展开 + 气泡隐身 → ✕ 收起还原
> - 心情选择器：右上浮出 · 6 标签 · 10s 超时回工具栏 pill（pill 可点击再开）
> - rail：磁吸右缘可拖 · 点击开时间线
> - 黑板：zoom 按钮全屏查看 · 粉笔逐帧绘制 + 光标跟随

> **插件化（二期）**：接口+注册表+配置拼装。`Live2DProvider{load,setExpression,speak,hit}` · `BoardTheme` · `ToolPlugin{id,title,icon,panel}` · registry 通用化。MVP 用默认实现。

---

## 3. 回合状态机

```
idle ──send user_input──▶ awaiting_first_frame
awaiting_first_frame ──first_frame──▶ collecting(清黑板/重置 seq/浮心情选择器)
collecting ──draw(增量)──▶ collecting(继续)
collecting ──充分度达标(后端停采集)──▶ analysis(显示"收尾中")
analysis ──draw(精稿)+text_delta──▶ final
final ──done──▶ idle
任意状态 ──error──▶ idle(温和兜底)
任意状态 ──新 first_frame──▶ collecting(新回合抢占,清黑板)
```

- **心情选择器**:collecting 开始时浮出,10s 超时自动收起;crisis 不浮
- **crisis**:first_frame(route=crisis)→ 显示热线横幅 + 支持性画面(stage_map)
- **analysis**:最后回答提交 → 精稿 draw 之间,前端显示"收尾中"(纯前端推断,无专用消息)

---

## 4. 模块接口(关键签名)

```ts
// ws/client.ts
connect(): Promise<void>
on(type: WSMsgType, handler: (msg: WSMsg) => void): void
send(msg: CSMsg): void          // user_input / mood_select

// board/renderer.ts
render(templateId: string, data: Formulation, seq: number): void
  // 读声明 → diff 新字段 → 动画补画;旧字段保留

// board/diff.ts
diff(prev: Formulation, next: Formulation): FieldKey[]
  // 返回新增/变化的字段(值变化也算)

// board/templateRegistry.ts
register(decl: TemplateDecl): void
get(templateId: string): TemplateDecl

// mood/selector.ts
show(): void   hide(): void   onSelect(mood: MoodKey): void  // → send mood_select

// l2d/live2d.ts
setExpression(emotionLabel: string): void   // 情绪标签 → 表情参数
speak(text: string): void                    // 可选:TTS 播放

// state/round.ts
transition(event: RSEvent): void
```

---

## 5. 关键难点骨架

### 5.1 模板声明类型(TS)

```ts
type Widget = "text" | "highlight" | "rough_ellipse+text" | "rough_box+text" | "wheel_mini";

interface FieldDecl {
  key: FormulationKey;         // situation/emotion/thought/behavior/intermediate_belief/core_belief
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
function render(templateId, data, seq):
  decl = registry.get(templateId)
  if seq > lastSeq:                        # 新帧
    changed = diff(lastData, data)         # 新填/变化的字段
    for key in changed:
      if data[key] == null: continue       # 留白格不画
      widget = decl.field(key).widget
      draw(widget, data[key])              # 动画补画 + chalk 光标跟随
    lastSeq = seq; lastData = data
```

### 5.3 回合状态机伪码

```
on WS message m:
  switch m.type:
    first_frame: round.reset(); round.enter("collecting")
                 if m.route == "crisis": showHotline(); board.render("stage_map")
                 else: mood.show(); board.render(m.template, 粗稿数据)
    draw:        board.render(m.template, m.data, m.seq)
    text_delta:  chat.append(m.text); if m.final: chat.finalize()
    audio_chunk: l2d.speak(m.data)
    done:        round.enter("idle"); mood.hide()
    error:       round.enter("idle"); chat.append(温和兜底话术)
```

---

## 6. WS 消息 → 前端行为(对应表)

| 消息 | 前端行为 |
|---|---|
| first_frame | 回合重置;crisis→热线+stage_map;collect→心情选择器+粗稿 |
| draw | 渲染器增量画(按 seq)|
| text_delta | 气泡流式追加 |
| audio_chunk | Live2D 语音播放 |
| done | 收尾:收起等待态 |
| error | 温和兜底,回 idle |
| user_input(发)| 触发新回合 |
| mood_select(发)| 上报心情 |

---

## 7. 验收(前端视角,3 用例)

1. **answer**:输入"什么是正念" → 无黑板,气泡流式文本,结束
2. **collect**:输入"最近很焦虑睡不着" → 第一帧 → 心情选择器(10s 超时回退)→ 黑板粗稿 → 逐轮增量 → 精稿补全 → 分析总结+心灵补给站邀请语(方案书=点击补给站触发生成)
3. **crisis**:输入"我不想活了" → 热线横幅 + stage_map,不弹心情选择器
