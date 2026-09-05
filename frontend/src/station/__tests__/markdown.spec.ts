// renderMarkdown 钉测试:受控子集(标题/列表/引用/加粗/段落)+ HTML 转义 + CRLF。
import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../markdown'

describe('renderMarkdown', () => {
  it('标题三档', () => {
    expect(renderMarkdown('# 大')).toBe('<h1>大</h1>')
    expect(renderMarkdown('## 中')).toBe('<h2>中</h2>')
    expect(renderMarkdown('### 小')).toBe('<h3>小</h3>')
  })

  it('无序/有序列表成组闭合', () => {
    expect(renderMarkdown('- a\n- b')).toBe('<ul><li>a</li><li>b</li></ul>')
    expect(renderMarkdown('1. 甲\n2. 乙')).toBe('<ol><li>甲</li><li>乙</li></ol>')
    expect(renderMarkdown('- a\n# 标')).toBe('<ul><li>a</li></ul><h1>标</h1>') // 标题前闭合列表
  })

  it('引用块与加粗', () => {
    expect(renderMarkdown('> 声明行')).toBe('<blockquote>声明行</blockquote>')
    expect(renderMarkdown('**重点**内容')).toBe('<p><strong>重点</strong>内容</p>')
  })

  it('HTML 整体转义(产物进 v-html 的安全前提)', () => {
    expect(renderMarkdown('<script>x</script>')).toBe('<p>&lt;script&gt;x&lt;/script&gt;</p>')
    expect(renderMarkdown('- <b>&')).toBe('<ul><li>&lt;b&gt;&amp;</li></ul>')
  })

  it('CRLF 输入不产生残渣', () => {
    expect(renderMarkdown('# 标\r\n\r\n- 项')).toContain('<h1>标</h1>')
    expect(renderMarkdown('# 标\r\n\r\n- 项')).toContain('<li>项</li>')
    expect(renderMarkdown('# 标\r\n\r\n- 项')).not.toContain('\r')
  })

  it('空行分段', () => {
    expect(renderMarkdown('上段\n\n下段')).toBe('<p>上段</p><p>下段</p>')
  })
})
