/**
 * QR / pairing-URL parsing for the companion (Phase 4 QR connect).
 *
 * The desktop's Settings → Network card already renders a QR whose payload
 * is a `syncflow://pair?host=..&port=..&code=..` deep link (see
 * backend/pairing.py pair_qr + ws_bridge pairing:generate). This module
 * turns that (or a bare ws:// URL carrying ?code=) into the exact shape
 * connectCompanion() expects — three consume paths:
 *
 *   1. in-app camera scan (Capacitor ML Kit, ConnectScreen "Scan QR")
 *   2. system camera scans the QR -> Android/iOS opens the app via the
 *      syncflow:// scheme intent (src/lib/deepLink.ts)
 *   3. manual typing (always available as the fallback)
 */

export interface PairTarget {
  /** Full ws:// URL, e.g. ws://192.168.1.20:18973 */
  host: string
  port: number
  /** Uppercased pairing code, same shape the desktop mints (B32, len 8). */
  code: string
}

const CODE_RE = /^[A-Z2-7]{8}$/
const HOST_RE = /^[A-Za-z0-9.\-:]{1,64}$/

function buildHost(ip: string, port: number): string | null {
  if (!HOST_RE.test(ip) || ip.includes('..')) return null
  if (!Number.isInteger(port) || port < 1 || port > 65535) return null
  const bracketed = ip.includes(':') && !ip.startsWith('[') ? `[${ip}]` : ip
  return `ws://${bracketed}:${port}`
}

function fromParams(params: URLSearchParams): PairTarget | null {
  const ip = (params.get('host') || '').trim()
  const code = (params.get('code') || '').trim().toUpperCase()
  const portParam = params.get('port')
  const port = portParam ? Number(portParam) : 18973
  if (!ip || !CODE_RE.test(code)) return null
  const host = buildHost(ip, port)
  if (!host) return null
  return { host, port, code }
}

/** Parse a scanned/opened string into a pair target; null if not ours. */
export function parsePairQr(text: string): PairTarget | null {
  if (typeof text !== 'string') return null
  const raw = text.trim()
  if (!raw) return null
  try {
    if (raw.startsWith('syncflow://')) {
      const u = new URL(raw)
      // syncflow://pair?... -> host is the scheme's opaque authority ("pair")
      return fromParams(u.searchParams)
    }
    if (raw.startsWith('ws://') || raw.startsWith('wss://')) {
      const u = new URL(raw)
      const target = fromParams(u.searchParams)
      if (target) {
        // keep the URL's own authority; only the code came from params
        return { host: `${u.protocol}//${u.host}`, port: Number(u.port) || 18973, code: target.code }
      }
    }
  } catch {
    /* malformed URL — fall through */
  }
  return null
}
