import { Capacitor } from '@capacitor/core'
import { parsePairQr, type PairTarget } from './qr'

/**
 * Deep-link pairing (QR connect path #2): the phone's system camera (or
 * any browser) opens `syncflow://pair?...` and Android/iOS route it to
 * this app via the scheme's intent filter / URL type. The ConnectScreen
 * listens for the `syncflow:pair` event (or takes the launch URL) and
 * auto-fills + connects.
 *
 * Only meaningful on native — the web companion has no scheme handler,
 * so init is a no-op there (scan/manual entry still work).
 */

let pending: PairTarget | null = null
const listeners = new Set<(t: PairTarget) => void>()

export function takePendingPair(): PairTarget | null {
  const p = pending
  pending = null
  return p
}

export function onPendingPair(cb: (t: PairTarget) => void): () => void {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

function accept(url: string | undefined): void {
  if (!url) return
  const target = parsePairQr(url)
  if (!target) return
  pending = target
  listeners.forEach((cb) => {
    try {
      cb(target)
    } catch {
      /* a bad listener must not break delivery */
    }
  })
  // Also dispatch for components not wired through onPendingPair.
  window.dispatchEvent(new CustomEvent<PairTarget>('syncflow:pair', { detail: target }))
}

/** Call once at startup in companion mode; no-op on the web build. */
export async function initDeepLinks(): Promise<void> {
  if (!Capacitor.isNativePlatform()) return
  try {
    const { App } = await import('@capacitor/app')
    await App.addListener('appUrlOpen', (ev) => accept(ev.url))
    const launch = await App.getLaunchUrl()
    accept(launch?.url)
  } catch {
    /* app plugin missing — deep links simply unavailable */
  }
}
