// UI screenshot helper for Claude Code / local design review.
//
// Spawns system Chrome headless, navigates to a route on the dev server,
// suppresses the first-visit tour overlay, and writes a PNG. No npm deps:
// uses Node's global fetch + WebSocket and the Chrome already on the machine.
//
// Usage:
//   node scripts/shot.mjs [route] [outfile] [--full] [--w=1440] [--h=900]
//
// Examples:
//   node scripts/shot.mjs / /tmp/home.png --full
//   node scripts/shot.mjs /projects/2/setup /tmp/setup.png
//   npm run shot -- /projects/2/prompt-lab /tmp/lab.png --full
//
// Then Read the PNG. Override the dev server with BASE_URL, Chrome with
// CHROME_BIN. The script picks a free-ish debug port and cleans up Chrome.

import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const args = process.argv.slice(2)
const positional = args.filter(a => !a.startsWith('--'))
const flags = Object.fromEntries(
  args.filter(a => a.startsWith('--')).map(a => {
    const [k, v] = a.replace(/^--/, '').split('=')
    return [k, v ?? true]
  }),
)

const route = positional[0] || '/'
const out = positional[1] || '/tmp/annotagent-ui.png'
const baseUrl = process.env.BASE_URL || 'http://localhost:5173'
const width = Number(flags.w || 1440)
const height = Number(flags.h || 900)
const fullPage = !!flags.full
const port = 9300 + Math.floor((Date.now() % 600))
const url = baseUrl.replace(/\/$/, '') + route

const CHROME = process.env.CHROME_BIN ||
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

const profile = mkdtempSync(join(tmpdir(), 'annot-shot-'))
const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars',
  `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  `--window-size=${width},${height}`, url,
], { stdio: 'ignore' })

const cleanup = () => {
  try { chrome.kill('SIGKILL') } catch {}
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
}

async function cdp() {
  let target
  for (let i = 0; i < 80; i++) {
    try {
      const list = await (await fetch(`http://localhost:${port}/json/list`)).json()
      target = list.find(t => t.type === 'page' && t.webSocketDebuggerUrl)
      if (target) break
    } catch {}
    await new Promise(r => setTimeout(r, 150))
  }
  if (!target) throw new Error('Chrome devtools did not come up')

  const ws = new WebSocket(target.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  const send = (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id
    pending.set(mid, { res, rej })
    ws.send(JSON.stringify({ id: mid, method, params }))
  })
  await new Promise(res => ws.addEventListener('open', res))
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data)
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id)
      pending.delete(m.id)
      m.error ? rej(new Error(m.error.message)) : res(m.result)
    }
  })

  await send('Page.enable')
  await send('Runtime.enable')
  // Mark the onboarding tour as already seen BEFORE the app's JS runs, so the
  // welcome modal never mounts. An init script + fresh navigation is reliable;
  // setting localStorage after load and reloading races the React mount.
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: "try{localStorage.setItem('annotagent.tour.v1.done','1');localStorage.setItem('annotagent.tour.v1.active','0')}catch(e){}",
  })
  const loaded = new Promise(res => {
    const onMsg = ev => {
      const m = JSON.parse(ev.data)
      if (m.method === 'Page.loadEventFired') { ws.removeEventListener('message', onMsg); res() }
    }
    ws.addEventListener('message', onMsg)
  })
  await send('Page.navigate', { url })
  await Promise.race([loaded, new Promise(r => setTimeout(r, 6000))])
  await new Promise(r => setTimeout(r, 1600))

  let shotParams = { format: 'png' }
  if (fullPage) {
    const { cssContentSize } = await send('Page.getLayoutMetrics')
    shotParams = {
      format: 'png',
      captureBeyondViewport: true,
      clip: { x: 0, y: 0, width: cssContentSize.width, height: cssContentSize.height, scale: 1 },
    }
  }
  const { data } = await send('Page.captureScreenshot', shotParams)
  writeFileSync(out, Buffer.from(data, 'base64'))
  ws.close()
}

cdp()
  .then(() => { console.log(`Saved ${out}  (${url}${fullPage ? ', full page' : `, ${width}x${height}`})`); cleanup(); process.exit(0) })
  .catch(err => { console.error('shot failed:', err.message); cleanup(); process.exit(1) })
