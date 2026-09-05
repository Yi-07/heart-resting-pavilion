// Live2D 真立绘(步骤7;版本钉子=frontend-plan §1:pixi.js 6.5.10 +
// pixi-live2d-display 0.4.0,初始化参照 mockup L402-430)。
// 模型地址=候选序列(l2d/models.ts):本地 vendor 优先 → 上游 CDN 回退;
// 任何一步失败(核心脚本/模型全候选/渲染)→ 返回 null,App 落回 SVG 手绘兜底;
// pixi 走动态 import 懒加载,不进首屏包。真口型(音频幅值驱动)步骤8 接。

import { logger } from '../logger'
import type { AvatarExpr } from './placeholder'

export interface Live2DController {
  setExpression(expr: AvatarExpr): void
  setSpeaking(active: boolean): void
  destroy(): void
}

/** 表情→模型表情序号(mockup L2D_EXPR 同表;未知落 0 中性;非 haru 模型表情数不同,越界自动落 0) */
const EXPR_INDEX: Record<AvatarExpr, number> = {
  neutral: 0,
  calm: 0,
  warm: 1,
  tired: 3,
  worried: 3,
}

/** cubism core(index.html 本地 vendor 挂载,失败回退官方 CDN)就绪等待;超时按失败回退 */
function waitForCore(timeoutMs = 15000): Promise<boolean> {
  const startedAt = Date.now()
  return new Promise((resolve) => {
    const timer = window.setInterval(() => {
      if (window.Live2DCubismCore !== undefined) {
        window.clearInterval(timer)
        resolve(true)
      } else if (Date.now() - startedAt > timeoutMs) {
        window.clearInterval(timer)
        resolve(false)
      }
    }, 200)
  })
}

export async function createLive2D(
  stage: HTMLElement,
  canvas: HTMLCanvasElement,
  modelUrls: string[],
): Promise<Live2DController | null> {
  try {
    if (!(await waitForCore())) throw new Error('cubism core 未就绪(本地 vendor 与官方 CDN 均未达)')
    const PIXI = await import('pixi.js')
    window.PIXI = PIXI // pixi-live2d-display 运行时取全局 PIXI
    // 必须走 /cubism4 子路径:主入口是 Cubism2+4 全量构建,模块顶层硬要求
    // window.Live2D(Cubism 2 runtime),缺即抛——model3.json 均为 Cubism 4
    const { Live2DModel } = await import('pixi-live2d-display/cubism4')

    const app = new PIXI.Application({
      view: canvas,
      backgroundAlpha: 0,
      autoStart: true,
      resizeTo: stage,
      antialias: true,
    })
    let model: Awaited<ReturnType<typeof Live2DModel.from>> | null = null
    let lastErr: unknown = null
    for (const url of modelUrls) {
      try {
        model = await Live2DModel.from(url)
        break
      } catch (err) {
        lastErr = err
        logger.warn('l2d', `模型候选失败 ${url}: ${String(err)}`)
      }
    }
    if (model === null) throw new Error(`模型载入失败(候选 ${modelUrls.length} 个): ${String(lastErr)}`)
    app.stage.addChild(model)

    let bw = 600
    let bh = 700
    try {
      const b = model.getBounds()
      if (b.width > 0) bw = b.width
      if (b.height > 0) bh = b.height
    } catch {
      /* 取不到包围盒按经验值缩放 */
    }
    const s = Math.min((stage.clientWidth * 0.9) / bw, (stage.clientHeight * 0.95) / bh)
    model.scale.set(s)
    model.anchor.set(0.5, 0.98)
    model.x = stage.clientWidth / 2
    model.y = stage.clientHeight - 4

    model.on('hit', (areas: string[]) => {
      if (areas.includes('Body')) void model.motion('TapBody').catch(() => {})
    })

    logger.info('l2d', `Live2D 就绪(模型 ${bw}×${bh},缩放 ${s.toFixed(2)})`)

    return {
      setExpression(expr: AvatarExpr): void {
        try {
          model.expression(EXPR_INDEX[expr] ?? 0)
        } catch (err) {
          logger.warn('l2d', `表情切换失败: ${String(err)}`)
        }
      },
      setSpeaking(active: boolean): void {
        // MVP:播放中以点头动作示意;真口型随步骤8 音频幅值接入
        if (active) void model.motion('TapBody').catch(() => {})
      },
      destroy(): void {
        app.destroy(true)
      },
    }
  } catch (err) {
    logger.warn('l2d', `Live2D 加载失败,回退 SVG 立绘: ${String(err)}`)
    return null
  }
}
