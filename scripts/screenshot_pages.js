// 模拟真实用户：一次登录，之后全部通过 SPA 侧栏导航逐页截图
const path = require('path')
const fs = require('fs')
const puppeteer = require('C:/Users/francis/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core')

const BASE = 'http://127.0.0.1:5000'
const OUT = 'D:/MyBuddy/EdgeControl/docs/screenshots'
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const TOKEN_FILE = 'D:/MyBuddy/EdgeControl/scripts/_ec_token.json'
const TOKEN = process.env.EC_TOKEN
  || (fs.existsSync(TOKEN_FILE) ? JSON.parse(fs.readFileSync(TOKEN_FILE, 'utf8')).token : '')

const PAGES = [
  ['dashboard',   '总览看板'],
  ['nodes',       '节点管理'],
  ['monitor',     '数据监控'],
  ['media',       '媒体资产'],
  ['alerts',      '告警中心'],
  ['commands',    '控制中心'],
  ['system',      '系统运维'],
  ['users',       '用户权限']
]

;(async () => {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await puppeteer.launch({ executablePath: EDGE, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1680,1050'] })
  const page = await browser.newPage()
  await page.setViewport({ width: 1680, height: 1050 })

  const errors = []
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))
  page.on('response', (r) => { if (r.status() >= 400) errors.push(r.status() + ' ' + r.url()) })

  // 1) 登录页截图（真实访问）
  await page.goto(BASE + '/login', { waitUntil: 'networkidle2' })
  await new Promise((r) => setTimeout(r, 1500))
  await page.screenshot({ path: path.join(OUT, 'login.png') })
  console.log('  [shot] login')

  // 2) 注入 token 进入控制台（等价于真实登录后的状态）
  await page.evaluate((t) => localStorage.setItem('novaedge_token', t), TOKEN)
  await page.goto(BASE + '/dashboard', { waitUntil: 'networkidle2' })
  await new Promise((r) => setTimeout(r, 2500))

  // 3) SPA 导航逐页截图：优先点侧栏，节点详情用页面内链接
  let ok = 0
  for (const [name] of PAGES) {
    const via = await page.evaluate((n) => {
      const a = document.querySelector(`aside a[href="/${n}"]`)
      if (a) { a.click(); return 'sidebar' }
      return null
    }, name)
    if (!via) { console.log(`  [skip] /${name} 无侧栏入口`); continue }
    await page.waitForFunction((n) => location.pathname === '/' + n, { timeout: 20000 }, name).catch(() => {})
    await new Promise((r) => setTimeout(r, 2800))
    const landed = new URL(page.url()).pathname
    const good = landed === '/' + name
    if (good) ok += 1
    await page.screenshot({ path: path.join(OUT, `${name}.png`) })
    console.log(`  [shot] ${name.padEnd(11)} 落地=${landed.padEnd(14)} ${good ? 'OK' : '!!异常'}`)
  }

  // 4) 节点详情页（从节点管理页点进第一行）
  await page.evaluate(() => { const a = document.querySelector('aside a[href="/nodes"]'); a && a.click() })
  await new Promise((r) => setTimeout(r, 2200))
  await page.evaluate(() => {
    const a = document.querySelector('a[href^="/nodes/"]')
    a && a.click()
  })
  await new Promise((r) => setTimeout(r, 2800))
  const detailPath = new URL(page.url()).pathname
  await page.screenshot({ path: path.join(OUT, 'node-detail.png') })
  console.log(`  [shot] node-detail 落地=${detailPath}`)
  if (detailPath.startsWith('/nodes/')) ok += 1

  console.log('\n=== 异常与错误 ===')
  if (errors.length === 0) console.log('  无')
  else [...new Set(errors)].slice(0, 15).forEach((e) => console.log('  !!', e))

  await browser.close()
  console.log(`\nSPA 流程：${ok}/10 页正常`)
})()
