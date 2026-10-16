// 10 种 WS 消息类型定义,严格对齐 docs/architecture/ws-contract.md(类型单源)。
// 改契约先改 ws-contract,再同步本文件与 backend/app/schema/。

/** 路由三值(契约 §5.2) */
export type Route = 'answer' | 'collect' | 'crisis'

/** 模板 id(契约 §5.2);beck=MVP 采集默认,wheel/stage_map=测试模板,scene_*=黑板场景化板式 */
export type TemplateId = 'beck_formulation' | 'emotion_wheel' | 'stage_map' | 'scene_default' | 'scene_focus' | 'scene_answer' | 'scene_crisis'

/** 心情六档(契约 §4.2) */
export type MoodKey = '难过' | '低落' | '平静' | '还好' | '开心' | '很好'

/** error 帧 code(契约 §3.8) */
export type ErrorCode = 'invalid_message' | 'timeout' | 'server_error' | 'ask_llm_failed'

// ---------- 数据对象(契约 §5.1) ----------

/** formulation.emotion 子对象;label/intensity 均可 null(研判无强度可缺省) */
export interface Emotion {
  label: string | null
  intensity: number | null
}

/** beck_formulation 黑板数据(六字段);未采字段=null(不画该格,belief 允许留白) */
export interface Formulation {
  situation: string | null
  emotion: Emotion
  thought: string | null
  behavior: string | null
  intermediate_belief: string | null
  core_belief: string | null
}

export interface EmotionWheelDatum {
  label: string
  intensity: number // 0~1
  color: string
}

/** emotion_wheel 测试模板 data */
export interface EmotionWheelData {
  emotions: EmotionWheelDatum[]
}

/** stage_map 测试模板 data */
export interface StageMapData {
  nodes: string[]
  current: number
  from: string
}

/** scene_* 板式 collect 用:六字段同 formulation + 展示选材(assets 不进 formulation 域对象,归档不混选材) */
export interface SceneFormulationData extends Formulation {
  /** 字段 key → 图标 id,仅选中字段携带;可缺省(缺省该位不画,无默认兜底);
   *  subject=画面主体选材,与字段键平等(有贴切才选;画不画由选材定,画哪多大由 zones.subject 声明) */
  assets?: Partial<Record<keyof Formulation, string>> & { subject?: string }
}

/** scene_answer/scene_crisis 固定场景 data:图标预绑定在模板声明,只携底部注释行 */
export interface SceneNoteData {
  note: string | null
}

/** draw.data 五型联合,随 template 取其一 */
export type TemplateData = Formulation | EmotionWheelData | StageMapData | SceneFormulationData | SceneNoteData

// ---------- S→C(契约 §3) ----------

/** 新回合起点(清黑板/重置 seq 基线/收起选择器计时);answer 型不发 */
export interface FirstFrame {
  type: 'first_frame'
  session_id: string
  round_id?: string | null // collect 才有;crisis 无;本轮采集稳定标识(契约 §3.1)
  route: Exclude<Route, 'answer'>
  template: TemplateId | null // collect 才有;crisis=null
  emotion_label: string | null
  mood_select: boolean // 恒 false:自动浮出已废弃,心情上报走「今日心情」按钮(契约 §3.1/§4.2)
  text: string
}

/** 黑板绘制;data=完整 formulation(非增量),前端按 seq 差动画 */
export interface Draw {
  type: 'draw'
  seq: number // 会话内全局递增(§3.2)
  template: TemplateId
  data: TemplateData
}

/** 流式回复文本;final=true 标记最后一块(可不依赖) */
export interface TextDelta {
  type: 'text_delta'
  seq: number
  text: string
  final: boolean
}

/** 音频编码；决定前端走哪条播放链路（见 audio/index.ts 的分派） */
export type AudioFormat = 'wav' | 'pcm_s16le'

/** TTS 音频块（base64） */
export interface AudioChunk {
  type: 'audio_chunk'
  seq: number
  format: AudioFormat
  data: string
  final: boolean
  /** TTS round_id；PCM 流式下用于回合隔离，旧 round 的迟到帧直接丢 */
  round_id?: string
  /** round 内单调递增的块序号；PCM 流式下用于保序，不跨句重置 */
  audio_seq?: number
  /** PCM 采样率（Hz）；缺省表示该帧不是 PCM（旧帧不含此字段） */
  sample_rate?: number
  channels?: number
}

/** 回合结束;session_id 随 first_frame/done 带回(§1) */
export interface Done {
  type: 'done'
  session_id: string
  seq: number
  /** collect 回合结束带回的本轮标识(契约 §3.5);answer/crisis 无 */
  round_id?: string | null
  /** 仅 collect Finish 携带:本轮素材是否归档成功;false=不得启用该轮报告入口 */
  station_ready?: boolean | null
}

/** 错误帧;不带 seq 不消耗号 */
export interface ErrorFrame {
  type: 'error'
  code: ErrorCode
  message: string
}

/** 重连回放帧(契约 §3.6,ADR-005);无 seq 不进回合计数 */
export interface ReplayFrame {
  type: 'replay'
  mode: 'bubbles' | 'digest'
  /** mode=bubbles 携带:最近轮次原话(≤20 轮,降饱和回放) */
  turns?: { role: 'user' | 'assistant'; text: string }[]
  /** 温层最新摘要;digest 必有,bubbles 可 null */
  summary: string | null
  session_id: string
}

/** 留言墙回复就绪通知(契约 §3.7);无 seq 不进回合计数、不进回放。
 * 不携留言内容(内容单源 REST /wall 列表),收到即拉取刷新 */
export interface WallReplyFrame {
  type: 'wall_reply'
  session_id: string
}

export type S2CMsg =
  | FirstFrame
  | Draw
  | TextDelta
  | AudioChunk
  | Done
  | ErrorFrame
  | ReplayFrame
  | WallReplyFrame

// ---------- C→S(契约 §4) ----------

/** 用户文本输入;语音经 /asr/transcribe 转写回填后同此发送(ADR-004,输入单源文本) */
export interface UserInput {
  type: 'user_input'
  session_id?: string | null // 重连时带原 id;首条可省(连接即建会话,§1)
  text: string
  ts: number
}

/** 心情选择上报(六档) */
export interface MoodSelect {
  type: 'mood_select'
  session_id?: string | null
  mood: MoodKey
  ts: number
}

export type CSMsg = UserInput | MoodSelect

export type WSMsg = S2CMsg | CSMsg
export type WSMsgType = WSMsg['type']
