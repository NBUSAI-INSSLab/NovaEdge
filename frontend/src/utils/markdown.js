/**
 * 轻量 Markdown 渲染器（零依赖，面向智能管家报告）。
 * 支持：标题 / 表格 / 无序有序列表 / 引用 / 粗体 / 行内代码 / 分隔线 / 段落。
 * 输出前对原文做 HTML 转义，杜绝注入。
 */

function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
}

export function renderMarkdown(md) {
  if (!md) return ''
  const lines = String(md).replace(/\r\n/g, '\n').split('\n')
  const out = []
  let i = 0

  const isTableSep = (l) => /^\s*\|?\s*:?-{2,}[-:|\s]*\|?\s*$/.test(l) && l.includes('|')

  while (i < lines.length) {
    const line = lines[i]

    // 空行
    if (!line.trim()) { i++; continue }

    // 分隔线
    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { out.push('<hr />'); i++; continue }

    // 标题
    const h = line.match(/^(#{1,4})\s+(.*)$/)
    if (h) {
      const level = h[1].length
      out.push(`<h${level}>${inline(h[2])}</h${level}>`)
      i++
      continue
    }

    // 表格：当前行含 | 且下一行是分隔行
    if (line.includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const parseRow = (l) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
      const header = parseRow(line)
      i += 2
      const rows = []
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        rows.push(parseRow(lines[i]))
        i++
      }
      let html = '<table><thead><tr>'
      header.forEach((c) => { html += `<th>${inline(c)}</th>` })
      html += '</tr></thead><tbody>'
      rows.forEach((r) => {
        html += '<tr>'
        for (let k = 0; k < header.length; k++) html += `<td>${inline(r[k] || '')}</td>`
        html += '</tr>'
      })
      html += '</tbody></table>'
      out.push(html)
      continue
    }

    // 引用
    if (/^\s*>\s?/.test(line)) {
      const buf = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ''))
        i++
      }
      out.push(`<blockquote>${inline(buf.join(' '))}</blockquote>`)
      continue
    }

    // 无序列表
    if (/^\s*[-*]\s+/.test(line)) {
      let html = '<ul>'
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        html += `<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ''))}</li>`
        i++
      }
      out.push(html + '</ul>')
      continue
    }

    // 有序列表
    if (/^\s*\d+\.\s+/.test(line)) {
      let html = '<ol>'
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        html += `<li>${inline(lines[i].replace(/^\s*\d+\.\s+/, ''))}</li>`
        i++
      }
      out.push(html + '</ol>')
      continue
    }

    // 段落（合并连续行）
    const buf = [line]
    i++
    while (i < lines.length && lines[i].trim() &&
           !/^\s*(#{1,4}\s|>|\d+\.\s|[-*]\s|---)/.test(lines[i]) && !lines[i].includes('|')) {
      buf.push(lines[i])
      i++
    }
    out.push(`<p>${inline(buf.join('<br />'))}</p>`)
  }
  return out.join('\n')
}
