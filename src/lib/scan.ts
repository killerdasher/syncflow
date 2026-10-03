import { Capacitor } from '@capacitor/core'
import { parsePairQr, type PairTarget } from './qr'

/**
 * In-app QR scanning (QR connect path #1): ML Kit's ready-to-use native
 * scanner reads the desktop's `syncflow://pair?...` code and returns the
 * parsed target. Falls back with a typed message when the camera or the
 * Google barcode module is unavailable — the ConnectScreen always keeps
 * manual entry (and system-camera deep links) as alternatives.
 */
export async function scanPairQr(): Promise<PairTarget | null> {
  const { BarcodeScanner } = await import('@capacitor-mlkit/barcode-scanning')
  const sup = await BarcodeScanner.isSupported().catch(() => ({ supported: false }))
  if (!sup.supported) {
    throw new Error('This device has no camera available for scanning.')
  }
  if (Capacitor.getPlatform() === 'ios') {
    // Android's scan() runs through Google Play services (no explicit
    // CAMERA prompt); iOS needs the permission dialog up front.
    await BarcodeScanner.requestPermissions().catch(() => undefined)
  }
  let result
  try {
    result = await BarcodeScanner.scan()
  } catch (e: any) {
    const msg = String(e?.message || e)
    if (/permission|denied/i.test(msg)) {
      throw new Error('Camera permission denied — allow the camera or type the code.')
    }
    throw new Error('Scanner unavailable — enter the pairing code manually.')
  }
  const raw = result?.barcodes?.[0]?.displayValue || ''
  return parsePairQr(raw)
}
