/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 WS 地址,默认 ws://localhost:8000/ws */
  readonly VITE_WS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
