/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 WS 地址,默认 ws://localhost:8000/ws */
  readonly VITE_WS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/** pixi-live2d-display 0.4.0 自带类型不含 cubism 运行时全局,此处补窗口声明 */
interface Window {
  PIXI: unknown
  Live2DCubismCore: unknown
}

/** 最小面声明:npm 包类型与 pixi.js 6 泛型对不齐,只钉本项目用到的表面。
 *  注意走 /cubism4 子路径(主入口顶层硬要求 Cubism 2 runtime,见 live2d.ts) */
declare module 'pixi-live2d-display/cubism4' {
  import type { Container, Rectangle } from 'pixi.js'

  export class Live2DModel extends Container {
    static from(source: string, options?: Record<string, unknown>): Promise<Live2DModel>
    anchor: { set(x?: number, y?: number): void }
    expression(id: number | string): unknown
    motion(group: string, index?: number, priority?: unknown): Promise<boolean>
    getBounds(skipUpdate?: boolean, rect?: Rectangle): Rectangle
    on(event: 'hit', cb: (hitAreas: string[]) => void): this
  }
}
