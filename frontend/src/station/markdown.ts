// station/markdown.ts —— 迷你 markdown 渲染(零依赖):方案书由后端 planner 生成,
// 子集受控——标题(#{1,3})/无序有序列表/引用块/加粗/段落。
// 输入先整体 HTML 转义再拼标签,产物进 v-html 安全;换行按 \r?\n 切(文本可能带 CRLF)。

export function renderMarkdown(md: string): string {
  const inline = (s: string): string =>
    s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')

  const out: string[] = []
  let list: 'ul' | 'ol' | null = null
  const closeList = (): void => {
    if (list !== null) {
      out.push(`</${list}>`)
      list = null
    }
  }

  for (const raw of md.split(/\r?\n/)) {
    const line = raw.trimEnd()
    if (line === '') {
      closeList()
      continue
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line)
    if (heading !== null) {
      const [hashes, text] = [heading[1], heading[2]]
      if (hashes !== undefined && text !== undefined) {
        closeList()
        out.push(`<h${hashes.length}>${inline(text)}</h${hashes.length}>`)
        continue
      }
    }
    if (/^-\s+/.test(line)) {
      if (list !== 'ul') {
        closeList()
        out.push('<ul>')
        list = 'ul'
      }
      out.push(`<li>${inline(line.replace(/^-\s+/, ''))}</li>`)
      continue
    }
    const ordered = /^(\d+)[.、]\s*(.*)$/.exec(line)
    if (ordered !== null) {
      const text = ordered[2]
      if (list !== 'ol') {
        closeList()
        out.push('<ol>')
        list = 'ol'
      }
      out.push(`<li>${inline(text ?? '')}</li>`)
      continue
    }
    if (line.startsWith('> ')) {
      closeList()
      out.push(`<blockquote>${inline(line.slice(2))}</blockquote>`)
      continue
    }
    closeList()
    out.push(`<p>${inline(line)}</p>`)
  }
  closeList()
  return out.join('')
}
