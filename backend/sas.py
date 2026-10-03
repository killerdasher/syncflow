"""Short Authentication String (SAS) for out-of-band pairing verification.

Both devices independently derive the same 16-icon sequence from the pair
of their device IDs. The IDs themselves are public (each is the SHA-256
digest of a signing key already exchanged during pairing), so what the
ritual actually proves is: "the device sitting next to me holds the *same*
pair of IDs I am talking to" — i.e. it defeats a man-in-the-middle that
would have had to substitute its own key at pairing time.

Algorithm (stable — do not change without a protocol version bump):

    combined   = "".join(sorted([id_a, id_b]))      # order-independent
    digest     = sha256(combined).digest()          # 32 bytes
    first 12   = digest[:12]                        # 96 bits
    codes[i]   = 6-bit group i of first 12 bytes    # 16 codes, 0..63

The 16 codes are rendered by the UI as 16 icons (icon set lives in the
renderer, so both sides must ship the same alphabet — icons are an index
into that shared list). The full digest is also returned as hex so a
longer fingerprint can be compared for high-assurance setups.
"""

import hashlib
import re

DEVICE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
ICON_COUNT = 16
ICON_BITS = 6          # base-64 -> codes in 0..63
ICON_BYTES = ICON_COUNT * ICON_BITS // 8   # 96 bits = 12 bytes


def compute_sas(id_a: str, id_b: str) -> dict:
    """Return {"codes": [...], "hash": hex} for the pair of device IDs.

    Raises ValueError on malformed device IDs. Both IDs must be the
    32-char lowercase hex form produced by sha256_str(...)[:32].
    """
    for value, label in ((id_a, "a"), (id_b, "b")):
        if not isinstance(value, str) or not DEVICE_ID_RE.match(value):
            raise ValueError(f"invalid device id {label}")
    if id_a == id_b:
        raise ValueError("device ids must differ")

    combined = "".join(sorted((id_a, id_b)))
    digest = hashlib.sha256(combined.encode("ascii")).digest()

    # 96 bits, MSB-first, split into 16 base-64 digits.
    bits = int.from_bytes(digest[:ICON_BYTES], "big")
    total_bits = ICON_COUNT * ICON_BITS
    shift = total_bits - ICON_BITS
    codes = [(bits >> (shift - ICON_BITS * i)) & 0x3F for i in range(ICON_COUNT)]

    return {"codes": codes, "hash": digest.hex()}
