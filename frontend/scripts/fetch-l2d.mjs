// fetch-l2d.mjs —— Live2D 素材本地化(零依赖,node>=18):
//   1) Cubism Core 运行时 → public/vendor/live2d/core/
//   2) 内置模型(model3.json → 解析 FileReferences 递归抓全)→ public/vendor/live2d/models/<id>/
//   3) 写目录清单 public/vendor/live2d/models.json(运行时切换器读;自定义模型=同名目录丢入+手工加一行)
// 素材授权禁止再分发 → 目录 gitignored,不入库;本脚本幂等(已存在文件跳过)。
// 镜像链:fastly.jsdelivr.net(本机实测可达)→ cdn.jsdelivr.net;模型也可来自任意可直连 URL。
// 用法:node scripts/fetch-l2d.mjs

import { mkdir, writeFile, access, readFile } from 'node:fs/promises'
import { dirname, join, normalize } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const OUT = join(ROOT, 'public', 'vendor', 'live2d')

const MIRRORS = ['https://fastly.jsdelivr.net', 'https://cdn.jsdelivr.net']

const CORE_URL_PATH = '/sdk-web/cubismcore/live2dcubismcore.min.js'
const CORE_ORIGIN = 'https://cubism.live2d.com'

// 内置模型:source=jsdelivr gh 路径或完整 URL;default 决定运行时首选
const MODELS = [
  {
    id: 'haru',
    label: '小春',
    source:
      '/gh/guansss/pixi-live2d-display@master/test/assets/haru/haru_greeter_t03.model3.json',
    file: 'haru_greeter_t03.model3.json',
    default: true,
  },
  {
    id: 'hiyori',
    label: '日和',
    source: '/gh/Live2D/CubismWebSamples@develop/Samples/Resources/Hiyori/Hiyori.model3.json',
    file: 'Hiyori.model3.json',
  },
  {
    id: 'mao',
    label: '真樱',
    source: '/gh/Live2D/CubismWebSamples@develop/Samples/Resources/Mao/Mao.model3.json',
    file: 'Mao.model3.json',
  },
  {
    id: 'wanko',
    label: '汪汪',
    source: '/gh/Live2D/CubismWebSamples@develop/Samples/Resources/Wanko/Wanko.model3.json',
    file: 'Wanko.model3.json',
  },
]

const SAFE_EXT = /\.(moc3|png|json|wav|mp3)$/i

async function exists(p) {
  try {
    await access(p)
    return true
  } catch {
    return false
  }
}

/** 依次试镜像(fastly 间歇重置→3 轮退避);任一可达镜像 404=上游确无此文件返回 null;
 *  仅纯网络错才耗尽重试后抛 */
async function fetchAny(urlPaths, { origin } = {}) {
  let lastErr = null
  for (let attempt = 0; attempt < 3; attempt += 1) {
    let saw404 = false
    for (const up of urlPaths) {
      const url = origin !== undefined && up.startsWith('/') ? origin + up : up
      try {
        const res = await fetch(url)
        if (res.status === 404) {
          saw404 = true // 可达镜像明确说没有 → 权威(如 guansss 仓缺 cdi3)
          continue
        }
        if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`)
        return { buf: Buffer.from(await res.arrayBuffer()), url }
      } catch (err) {
        lastErr = err
      }
    }
    if (saw404) return null
    await new Promise((r) => setTimeout(r, 600 * (attempt + 1)))
  }
  throw lastErr instanceof Error ? lastErr : new Error(String(lastErr))
}

async function download(urlPaths, dest, { origin } = {}) {
  if (await exists(dest)) {
    console.log(`  跳过(已存在) ${dest.slice(ROOT.length + 1)}`)
    return
  }
  const got = await fetchAny(urlPaths, { origin })
  if (got === null) {
    console.log(`  缺(上游 404,运行时容忍) ${dest.slice(ROOT.length + 1)}`)
    return
  }
  await mkdir(dirname(dest), { recursive: true })
  await writeFile(dest, got.buf)
  console.log(`  ✓ ${(got.buf.length / 1024).toFixed(0)}KB ${dest.slice(ROOT.length + 1)}`)
}

/** 从 model3.json 的 FileReferences 递归收集引用文件(Sound 类不抓) */
function collectRefs(node, out) {
  if (node === null || typeof node !== 'object') return
  for (const [key, val] of Object.entries(node)) {
    if (typeof val === 'string') {
      if (key !== 'Sound' && SAFE_EXT.test(val) && !val.startsWith('http')) out.add(val)
    } else {
      collectRefs(val, out)
    }
  }
}

async function fetchModel(model) {
  console.log(`模型 ${model.id}(${model.label}):`)
  const dir = join(OUT, 'models', model.id)
  const main = join(dir, model.file)
  await download(MIRRORS.map((m) => m + model.source), main)
  const spec = JSON.parse(await readFile(main, 'utf8'))
  const refs = new Set()
  collectRefs(spec.FileReferences, refs)
  const baseDir = model.source.slice(0, model.source.lastIndexOf('/') + 1)
  for (const ref of refs) {
    const rel = normalize(ref).replaceAll('\\', '/')
    await download(MIRRORS.map((m) => m + baseDir + rel), join(dir, rel))
  }
  return {
    id: model.id,
    label: model.label,
    file: model.file,
    source: MIRRORS[0] + model.source, // 运行时 CDN 回退地址(本地文件缺失时)
    ...(model.default ? { default: true } : {}),
  }
}

async function main() {
  console.log('== Cubism Core ==')
  await download([CORE_URL_PATH], join(OUT, 'core', 'live2dcubismcore.min.js'), {
    origin: CORE_ORIGIN,
  })

  console.log('== 模型 ==')
  const catalog = []
  for (const m of MODELS) {
    try {
      catalog.push(await fetchModel(m))
    } catch (err) {
      console.warn(`  ✗ ${m.id} 抓取失败(跳过,不影响其余): ${String(err)}`)
    }
  }

  await mkdir(OUT, { recursive: true })
  await writeFile(join(OUT, 'models.json'), JSON.stringify(catalog, null, 2))
  console.log(`== 完成:清单 ${catalog.length} 个模型 → public/vendor/live2d/models.json ==`)
}

main().catch((err) => {
  console.error(`抓取失败: ${String(err)}`)
  process.exit(1)
})
