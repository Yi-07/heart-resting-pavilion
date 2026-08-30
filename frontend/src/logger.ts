// console 彩色 logger(frontend-plan §2 logger 模块),仿后端 Loguru 风格。
// 服务名 hrp-frontend;INFO 默认,import.meta.env.DEV 下含 DEBUG。

type Level = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR'

const LEVEL_STYLE: Record<Level, string> = {
  DEBUG: 'color:#64748b',
  INFO: 'color:#16a34a',
  WARN: 'color:#ca8a04',
  ERROR: 'color:#dc2626',
}

function emit(level: Level, scope: string, msg: string): void {
  const time = new Date().toLocaleTimeString('sv-SE', { hour12: false })
  const head = `%c${time} ${level.padEnd(5)} hrp-frontend/${scope}`
  const styled = [head, LEVEL_STYLE[level], msg] as const
  switch (level) {
    case 'DEBUG':
    case 'INFO':
      console.log(...styled)
      break
    case 'WARN':
      console.warn(...styled)
      break
    case 'ERROR':
      console.error(...styled)
      break
  }
}

export const logger = {
  debug(scope: string, msg: string): void {
    if (import.meta.env.DEV) emit('DEBUG', scope, msg)
  },
  info(scope: string, msg: string): void {
    emit('INFO', scope, msg)
  },
  warn(scope: string, msg: string): void {
    emit('WARN', scope, msg)
  },
  error(scope: string, msg: string): void {
    emit('ERROR', scope, msg)
  },
}
