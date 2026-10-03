// Icon alphabet for the Short Authentication String (SAS).
//
// The backend derives 16 codes (0..63) from the pair of device IDs — see
// backend/sas.py for the algorithm. Both sides render the same codes with
// THIS list: it must stay byte-identical across releases (order and glyphs
// are part of the verification ritual), so append-only, never reorder.
//
// Chosen for distinct silhouettes at small sizes — no two icons share a
// recognisable shape family.

export const SAS_ICONS: string[] = [
  '🔷', '🔶', '♠️', '♣️',
  '♥️', '♦️', '🔑', '🗝️',
  '🛡️', '⚔️', '🗡️', '🏹',
  '⚓', '🪝', '🧵', '🪡',
  '🧩', '🎲', '🎯', '🪁',
  '🥁', '🎸', '🎺', '🎻',
  '⚽', '🏀', '⚾', '🎾',
  '🏐', '🏉', '🥏', '🪀',
  '🏓', '🏸', '🥊', '🎣',
  '🛹', '🎿', '🪂', '🏋️',
  '🤸', '🏃', '🧌', '🤖',
  '👾', '🛸', '🪐', '🌠',
  '🌊', '🔥', '❄️', '☀️',
  '🌈', '⭐', '🌙', '🍎',
  '🍌', '🍉', '🍇', '🍓',
  '🥥', '🥝', '🌶️', '🍄',
]

export function sasIconSet(codes: number[]): string[] {
  return codes.map((c) => SAS_ICONS[((c % 64) + 64) % 64] ?? '❓')
}

/** 16 codes -> grouped hex string for the high-assurance fallback view. */
export function sasHex(hash: string): string {
  return hash.replace(/(.{8})/g, '$1 ').trim()
}
