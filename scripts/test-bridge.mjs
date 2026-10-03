#!/usr/bin/env node
/**
 * Phase 1 companion bridge — drives src/lib/bridge.ts end-to-end in Node
 * against a freshly spawned LAN-mode backend:
 *
 *   1. mint a pairing code over loopback (desktop side, local-only gate)
 *   2. connectCompanion(lanUrl, code) -> 'paired' (remote peer must pair)
 *   3. initial fetch after auth delivers identity:info (queue flush proof)
 *   4. reconnect with the persisted token -> 'authed'
 *   5. forget + wrong code -> 'pair_fail:bad_code'
 *   6. re-pair, then the real uploadFiles() flow: announce -> binary
 *      chunks -> file-done -> finish -> transfer:new, delivered through
 *      the engine to this backend's own TCP listener and verified on disk
 *
 * Shims localStorage/window over Node globals, bundles the real bridge with
 * esbuild, and uses Node's built-in WebSocket — no browser needed.
 * Run: node scripts/test-bridge.mjs   (exit 0 = pass; skipped = no LAN IP)
 */
import { build } from 'esbuild'
import { spawn } from 'node:child_process'
import dgram from 'node:dgram'
import net from 'node:net'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const log = (...a) => console.log('[bridge-test]', ...a)
const fail = (msg) => {
  console.error('[bridge-test] FAIL:', msg)
  process.exit(1)
}
setTimeout(() => fail('overall timeout (60s)'), 60000).unref()

function lanIp() {
  return new Promise((resolve) => {
    const s = dgram.createSocket('udp4')
    s.on('error', () => {
      try {
        s.close()
      } catch {}
      resolve('127.0.0.1')
    })
    s.connect(80, '192.0.2.1', () => {
      let ip = '127.0.0.1'
      try {
        ip = s.address().address
      } catch {}
      s.close()
      resolve(ip)
    })
  })
}

async function freePort() {
  for (let i = 0; i < 50; i++) {
    const p = 19000 + Math.floor(Math.random() * 900)
    const free = await new Promise((res) => {
      const srv = net.createServer()
      srv.once('error', () => res(false))
      srv.listen(p, '127.0.0.1', () => srv.close(() => res(true)))
    })
    if (free) return p
  }
  throw new Error('no free port')
}

function waitPort(port, timeoutMs = 30000) {
  const t0 = Date.now()
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      const sock = net.connect(port, '127.0.0.1')
      sock.once('connect', () => {
        sock.destroy()
        resolve()
      })
      sock.once('error', () => {
        sock.destroy()
        if (Date.now() - t0 > timeoutMs) reject(new Error(`port ${port} never opened`))
        else setTimeout(tryOnce, 300)
      })
    }
    tryOnce()
  })
}

function pickPython() {
  const venv = join(root, 'backend', 'venv', 'bin', 'python3')
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN
  if (existsSync(venv)) return venv
  return process.platform === 'win32' ? 'python' : 'python3'
}

function wsRequest(url, msg, expectType, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url)
    const timer = setTimeout(() => {
      try {
        ws.close()
      } catch {}
      reject(new Error(`no ${expectType} within ${timeoutMs}ms`))
    }, timeoutMs)
    ws.onopen = () => ws.send(JSON.stringify(msg))
    ws.onmessage = (e) => {
      let m
      try {
        m = JSON.parse(String(e.data))
      } catch {
        return
      }
      if (m.type === expectType) {
        clearTimeout(timer)
        try {
          ws.close()
        } catch {}
        resolve(m)
      }
    }
    ws.onerror = () => {
      clearTimeout(timer)
      reject(new Error(`ws error contacting ${url}`))
    }
  })
}

async function main() {
  if (typeof WebSocket === 'undefined') fail('Node built-in WebSocket missing (need Node >= 22)')

  const ip = await lanIp()
  if (ip.startsWith('127.')) {
    console.log('[bridge-test] SKIPPED: no non-loopback LAN IP on this machine')
    process.exit(0)
  }

  // --- browser shims BEFORE the bundle is evaluated -----------------------
  if (process.env.BRIDGE_DEBUG) globalThis.__BRIDGE_DEBUG = 1
  globalThis.window = globalThis
  const mem = new Map()
  globalThis.localStorage = {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => mem.set(k, String(v)),
    removeItem: (k) => mem.delete(k),
    clear: () => mem.clear(),
  }

  // --- bundle the real bridge + Phase 3 upload helper ---------------------
  const bundleDir = mkdtempSync(join(tmpdir(), 'sfb-'))
  const outfile = join(bundleDir, 'bridge.bundle.mjs')
  const entry = join(bundleDir, 'entry.mjs')
  writeFileSync(
    entry,
    `export * from ${JSON.stringify(join(root, 'src', 'lib', 'bridge.ts'))}\n` +
      `export * from ${JSON.stringify(join(root, 'src', 'lib', 'upload.ts'))}\n`
  )
  await build({
    entryPoints: [entry],
    bundle: true,
    format: 'esm',
    platform: 'browser',
    target: 'es2020',
    outfile,
    logLevel: 'silent',
  })

  // --- spawn a LAN-mode backend ------------------------------------------
  const wsPort = await freePort()
  const tcpPort = await freePort()
  const home = mkdtempSync(join(tmpdir(), 'sfbhome-'))
  const backendLog = []
  const proc = spawn(pickPython(), ['-u', join(root, 'backend', 'main.py')], {
    env: {
      ...process.env,
      SYNCFLOW_HOME: home,
      SYNCFLOW_WS_HOST: '0.0.0.0',
      SYNCFLOW_WS_PORT: String(wsPort),
      SYNCFLOW_TCP_PORT: String(tcpPort),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  proc.stdout.on('data', (d) => backendLog.push(String(d)))
  proc.stderr.on('data', (d) => backendLog.push(String(d)))
  proc.on('exit', (code) => {
    if (code !== null && code !== 0) {
      writeFileSync(join(tmpdir(), 'bridge-backend.log'), backendLog.join(''))
    }
  })
  const cleanup = () => {
    try {
      proc.kill('SIGTERM')
    } catch {}
    try {
      rmSync(home, { recursive: true, force: true })
    } catch {}
  }
  process.on('exit', cleanup)

  try {
    await waitPort(wsPort)
  } catch (e) {
    writeFileSync(join(tmpdir(), 'bridge-backend.log'), backendLog.join(''))
    fail(`${e.message} — see /tmp/bridge-backend.log`)
  }
  log(`backend up: ws://127.0.0.1:${wsPort} (LAN ip ${ip})`)

  const desktopUrl = `ws://127.0.0.1:${wsPort}`
  const phoneUrl = `ws://${ip}:${wsPort}`

  // 1. desktop mints a code (loopback = local-only gate passes)
  const codeMsg = await wsRequest(desktopUrl, { type: 'pairing:generate' }, 'pairing:code')
  const code = codeMsg.code
  if (typeof code !== 'string' || code.length !== 8) fail(`bad minted code: ${JSON.stringify(code)}`)
  log(`minted pairing code ${code}`)

  // 2. run the real bridge as the phone would
  const bridge = await import(pathToFileURL(outfile).href)
  if (!bridge.IS_COMPANION) fail('IS_COMPANION false without electronAPI')
  bridge.installBridge()
  const api = globalThis.electronAPI
  if (!api || typeof api.send !== 'function') fail('installBridge did not expose electronAPI')

  const seen = []
  api.onMessage((m) => seen.push(m))

  const paired = await bridge.connectCompanion(phoneUrl, code)
  if (paired !== 'paired') fail(`expected 'paired', got '${paired}'`)
  if (!globalThis.localStorage.getItem('syncflow.token')) fail('token not persisted after pair_ok')
  log('pairing OK, token persisted')

  // 3. initial fetch after auth must deliver identity:info (flush proof)
  const deadline = Date.now() + 8000
  while (Date.now() < deadline && !seen.some((m) => m.type === 'identity:info')) {
    await new Promise((r) => setTimeout(r, 100))
  }
  if (!seen.some((m) => m.type === 'identity:info')) {
    fail(`post-auth fetch missing (saw: ${seen.map((m) => m.type).join(',') || 'nothing'})`)
  }
  log('post-auth initial fetch delivered identity:info')

  // 4. reconnect with only the persisted token
  const authed = await bridge.connectCompanion(phoneUrl)
  if (authed !== 'authed') fail(`expected 'authed' from saved token, got '${authed}'`)
  log('token reconnect OK')

  // 5. wrong code — mint a fresh one first so an active code exists to
  //    mismatch (after step 1 the original was consumed, single-use)
  await wsRequest(desktopUrl, { type: 'pairing:generate' }, 'pairing:code')
  bridge.forgetCompanion()
  const bad = await bridge.connectCompanion(phoneUrl, 'ZZZZZZZZ')
  if (bad !== 'pair_fail:bad_code') fail(`expected 'pair_fail:bad_code', got '${bad}'`)
  log('wrong code rejected correctly')

  // 6. renderer upload flow — auto-accept so delivery completes unattended,
  //    target = this backend's own TCP listener (loopback)
  await wsRequest(desktopUrl, { type: 'settings:apply', autoAccept: true }, 'settings:applied')
  await wsRequest(desktopUrl, { type: 'pairing:generate' }, 'pairing:code').then(async (m) => {
    const reauth = await bridge.connectCompanion(phoneUrl, m.code)
    if (reauth !== 'paired') fail(`expected 'paired' before upload, got '${reauth}'`)
  })
  const upName = `bridge-up-${Date.now()}-${Math.floor(Math.random() * 1e6)}.bin`
  const upBytes = Buffer.from(`syncflow-upload-test:${process.pid}:${Date.now()}:`).toString('base64')
  const payload = Buffer.concat([Buffer.from(upBytes.repeat(4000))]) // ~300 KB across 2 frames
  const receiveDir = join(process.env.HOME || process.env.USERPROFILE || '', 'Downloads', 'SyncFlow')
  const receivedPath = join(receiveDir, upName)
  const uploaded = await bridge.uploadFiles(
    [{ name: upName, path: upName, size: payload.length, type: 'application/octet-stream',
       blob: new Blob([payload]) }],
    { ip: '127.0.0.1', port: tcpPort },
    `tr-up-${Date.now()}`
  )
  if (!uploaded) {
    const types = seen.map((m) => m.type).slice(-8)
    fail(`uploadFiles returned false (recent frames: ${types.join(',') || 'none'})`)
  }
  // engine round trip: file lands in the default receive dir with our bytes
  const { createHash } = await import('node:crypto')
  const sha = createHash('sha256').update(payload).digest('hex')
  const t0 = Date.now()
  let delivered = false
  while (Date.now() - t0 < 8000) {
    try {
      const got = readFileSync(receivedPath)
      if (createHash('sha256').update(got).digest('hex') === sha) {
        delivered = true
        break
      }
    } catch {}
    await new Promise((r) => setTimeout(r, 200))
  }
  if (!delivered) {
    writeFileSync(join(tmpdir(), 'bridge-backend.log'), backendLog.join(''))
    const tail = seen.slice(-10).map((m) => `${m.type}${m.error ? ':' + m.error : ''}${m.status ? ':' + m.status : ''}`)
    fail(`uploaded file never arrived in the receive dir (frames: ${tail.join(' | ')}; log: /tmp/bridge-backend.log)`)
  }
  rmSync(receivedPath, { force: true })
  log('renderer upload delivered + sha256 matched')

  cleanup()
  console.log('[bridge-test] PASS (6 steps)')
  process.exit(0)
}

main().catch((e) => fail(e && e.stack ? e.stack : String(e)))
