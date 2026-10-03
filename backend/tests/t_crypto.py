"""Crypto round-trip proof — standalone, runs on every OS (no servers/ports).

Exercises the app's real primitives from backend/crypto/e2e.py:
X25519 ECDH agreement, HKDF directional keys, AES-256-GCM round-trip +
tamper detection, Ed25519 sign/verify + forgery rejection, the full signed
handshake (offer/accept/complete), replay/stale-offer rejection, and key
persistence with owner-only file modes.
"""
import os
import shutil
import stat
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from crypto.e2e import (
    DeviceIdentityKeys,
    SessionCrypto,
    handshake_accept,
    handshake_complete,
    handshake_offer,
    _signed_material,
)

PASS = 0
FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"PASS {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL += 1
        print(f"FAIL {name}  [{detail}]")


def fresh_identity():
    return DeviceIdentityKeys(storage_dir=tempfile.mkdtemp(prefix="sfcrypto-"))


def c1_ecdh_agreement():
    a, b = fresh_identity(), fresh_identity()
    s1, s2 = SessionCrypto(a), SessionCrypto(b)
    s1.derive_key(s2.ephemeral_pub_b64, initiator=True)
    s2.derive_key(s1.ephemeral_pub_b64, initiator=False)
    ok(
        "C1 X25519 ECDH: both sides derive matching directional keys",
        s1.key_send == s2.key_recv and s1.key_recv == s2.key_send and s1.key_send != s1.key_recv,
        f"sendA={s1.key_send[:6].hex()} recvB={s2.key_recv[:6].hex()}",
    )
    return a, b, s1, s2


def c2_gcm_roundtrip(a, b, s1, s2):
    msg = b"SyncFlow E2E payload \xf0\x9f\x94\x92" * 100
    blob = s1.encrypt(msg)
    out = s2.decrypt(blob)
    out2 = s1.decrypt(s2.encrypt(b"reply-direction"))
    ok(
        "C2 AES-256-GCM: bidirectional encrypt/decrypt round-trips",
        out == msg and out2 == b"reply-direction" and len(blob) == len(msg) + 12 + 16,
        f"len={len(blob)}",
    )

    tampered = bytearray(blob)
    tampered[-1] ^= 0x01
    try:
        s2.decrypt(bytes(tampered))
        tamper_detected = False
    except Exception:
        tamper_detected = True
    ok("C2b tampered ciphertext rejected (GCM auth tag)", tamper_detected, "")

    # Nonce must advance: two ciphertexts differ even for identical plaintext
    b1 = s1.encrypt(b"same")
    b2 = s1.encrypt(b"same")
    ok("C2c nonces never repeat (distinct ciphertexts)", b1 != b2, "")


def c3_ed25519(a, b):
    sig = a.sign(b"authorization payload")
    ok(
        "C3 Ed25519: signature verifies, forgery and wrong key rejected",
        a.verify(sig, b"authorization payload", a.signing_pub_b64)
        and not a.verify(sig, b"authorization payloaD", a.signing_pub_b64)
        and not b.verify(sig, b"authorization payload", b.signing_pub_b64),
        f"sig={sig[:12]}...",
    )


def c4_full_handshake(a, b):
    offer, sess_i = handshake_offer(a)
    accept, sess_r = handshake_accept(b, offer)
    ok_handshake = handshake_complete(a, accept, sess_i, initiator=True)
    wire = sess_i.encrypt(b"file-metadata.bin")
    back = sess_r.decrypt(wire)
    reply = sess_r.encrypt(b"chunk-1")
    got = sess_i.decrypt(reply)
    ok(
        "C4 signed handshake completes, session traffic flows both ways",
        ok_handshake and back == b"file-metadata.bin" and got == b"chunk-1",
        f"complete={ok_handshake}",
    )


def c5_replay_rejected(a, b):
    offer, _ = handshake_offer(a)
    stale = dict(offer, timestamp=time.time() - 600)
    stale_err = ""
    try:
        handshake_accept(b, stale)
        stale_ok = True
    except ValueError as e:
        stale_ok = False
        stale_err = str(e)[:60]

    forged = dict(offer)
    forged["signature"] = a.sign(b"wrong-material")
    forge_err = ""
    try:
        handshake_accept(b, forged)
        forge_ok = True
    except ValueError as e:
        forge_ok = False
        forge_err = str(e)[:60]

    ok(
        "C5 stale offer (replay) and forged signature rejected",
        not stale_ok and not forge_ok,
        f"stale={stale_err!r} forged={forge_err!r}",
    )


def c6_key_persistence(tmp_root):
    d = os.path.join(tmp_root, "identity")
    k1 = DeviceIdentityKeys(storage_dir=d)
    k2 = DeviceIdentityKeys(storage_dir=d)
    same = k1.signing_pub_b64 == k2.signing_pub_b64 and k1.x25519_pub_b64 == k2.x25519_pub_b64

    perms_ok = True
    detail = ""
    if sys.platform != "win32":
        for f in ("signing.key", "x25519.key"):
            mode = stat.S_IMODE(os.stat(os.path.join(d, f)).st_mode)
            if mode != 0o600:
                perms_ok = False
                detail += f"{f}={oct(mode)} "
        dmode = stat.S_IMODE(os.stat(d).st_mode)
        if dmode & 0o077:
            perms_ok = False
            detail += f"dir={oct(dmode)} "
    ok(
        "C6 identity persists across reloads, key files owner-only",
        same and perms_ok,
        detail or "identical pub keys on reload",
    )
    shutil.rmtree(tmp_root, ignore_errors=True)


def c7_security_suite(a, b):
    """ADR-0002 decision 3: handshake security suite is validated, fail-closed."""
    offer, sess_i = handshake_offer(a)

    missing_ok = unknown_ok = False
    missing = unknown = ""
    try:
        handshake_accept(b, {k: v for k, v in offer.items() if k != "security"})
        missing = "accepted"
    except ValueError as e:
        missing_ok = "security" in str(e)
        missing = str(e)[:60]
    try:
        handshake_accept(b, dict(offer, security="e2e-blockchain-v2"))
        unknown = "accepted"
    except ValueError as e:
        unknown_ok = "unsupported security suite" in str(e)
        unknown = str(e)[:60]
    ok(
        "C7a offer security suite validated (missing/unknown refused)",
        missing_ok and unknown_ok, f"missing={missing!r} unknown={unknown!r}",
    )

    accept, _ = handshake_accept(b, offer)
    bad_ok = False
    bad = ""
    try:
        handshake_complete(a, dict(accept, security="e2e-blockchain-v2"), sess_i, initiator=True)
        bad = "accepted"
    except ValueError as e:
        bad_ok = "unsupported security suite" in str(e)
        bad = str(e)[:60]
    ok("C7b unknown security suite in accept refused by initiator", bad_ok, bad)

    legacy = dict(accept)
    legacy.pop("security", None)
    legacy_ok = handshake_complete(a, legacy, sess_i, initiator=True) is True
    ok("C7c legacy accept without security still completes (additive policy)",
       legacy_ok, f"legacy={legacy_ok}")

if __name__ == "__main__":
    t = tempfile.mkdtemp(prefix="sfcrypto-main-")
    shutil.rmtree(t, ignore_errors=True)
    a, b, s1, s2 = c1_ecdh_agreement()
    c2_gcm_roundtrip(a, b, s1, s2)
    c3_ed25519(a, b)
    c4_full_handshake(a, b)
    c5_replay_rejected(a, b)
    c7_security_suite(a, b)
    c6_key_persistence(tempfile.mkdtemp(prefix="sfcrypto-persist-"))
    print(f"RESULTS_JSON: {{\"suite\": \"t_crypto\", \"pass\": {PASS}, \"fail\": {FAIL}}}")
    sys.exit(0 if FAIL == 0 else 1)
