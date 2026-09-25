import os
import json
import time
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _b64e(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")

def _b64d(data: str) -> bytes:
    import base64
    return base64.b64decode(data.encode("ascii"))


class DeviceIdentityKeys:
    """Long-term device identity: Ed25519 signing keypair + X25519 for ECDH."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = storage_dir or os.path.expanduser("~/.syncflow/identity")
        os.makedirs(self.storage_dir, exist_ok=True)

        sign_path = os.path.join(self.storage_dir, "signing.key")
        x25519_path = os.path.join(self.storage_dir, "x25519.key")

        if os.path.exists(sign_path):
            with open(sign_path, "rb") as f:
                self.signing_key = Ed25519PrivateKey.from_private_bytes(f.read())
        else:
            self.signing_key = Ed25519PrivateKey.generate()
            with open(sign_path, "wb") as f:
                f.write(self.signing_key.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                ))
            os.chmod(sign_path, 0o600)

        if os.path.exists(x25519_path):
            with open(x25519_path, "rb") as f:
                self.x25519_key = X25519PrivateKey.from_private_bytes(f.read())
        else:
            self.x25519_key = X25519PrivateKey.generate()
            with open(x25519_path, "wb") as f:
                f.write(self.x25519_key.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                ))
            os.chmod(x25519_path, 0o600)

        self.signing_pubkey = self.signing_key.public_key()
        self.x25519_pubkey = self.x25519_key.public_key()

    @property
    def signing_pub_b64(self) -> str:
        return _b64e(self.signing_pubkey.public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ))

    @property
    def x25519_pub_b64(self) -> str:
        return _b64e(self.x25519_pubkey.public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ))

    def sign(self, data: bytes) -> str:
        return _b64e(self.signing_key.sign(data))

    def verify(self, signature_b64: str, data: bytes, pubkey_b64: str) -> bool:
        try:
            pub = Ed25519PublicKey.from_public_bytes(_b64d(pubkey_b64))
            pub.verify(_b64d(signature_b64), data)
            return True
        except Exception:
            return False


class SessionCrypto:
    """Per-transfer E2E encryption: X25519 ECDH -> HKDF -> AES-256-GCM.

    Two directional keys are derived (initiator->responder and
    responder->initiator) so each AES key has exactly one encryptor and
    nonce reuse across directions is impossible. Identity is authenticated
    by Ed25519-signed handshakes with freshness checks; a MITM cannot
    forge signatures without the peer's long-term private key.
    """

    def __init__(self, identity: DeviceIdentityKeys):
        self.identity = identity
        self.ephemeral = X25519PrivateKey.generate()
        self.key_send: Optional[bytes] = None
        self.key_recv: Optional[bytes] = None
        self.nonce_counter = 0

    @property
    def ephemeral_pub_b64(self) -> str:
        return _b64e(self.ephemeral.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ))

    def derive_key(self, peer_ephemeral_pub_b64: str, initiator: bool) -> bytes:
        peer_pub = X25519PublicKey.from_public_bytes(_b64d(peer_ephemeral_pub_b64))
        shared = self.ephemeral.exchange(peer_pub)

        def kdf(direction: bytes) -> bytes:
            return HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"syncflow-e2e-v1",
                info=b"transfer-encryption|" + direction,
            ).derive(shared)

        k_i, k_r = kdf(b"i"), kdf(b"r")
        if initiator:
            self.key_send, self.key_recv = k_i, k_r
        else:
            self.key_send, self.key_recv = k_r, k_i
        return self.key_send

    def encrypt(self, plaintext: bytes) -> bytes:
        if not self.key_send:
            raise RuntimeError("Key not derived yet")

        self.nonce_counter += 1
        nonce = self.nonce_counter.to_bytes(12, "big")
        aesgcm = AESGCM(self.key_send)
        ct = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ct

    def decrypt(self, blob: bytes) -> bytes:
        if not self.key_recv:
            raise RuntimeError("Key not derived yet")
        if len(blob) < 12:
            raise ValueError("ciphertext too short")

        nonce = blob[:12]
        ct = blob[12:]
        aesgcm = AESGCM(self.key_recv)
        return aesgcm.decrypt(nonce, ct, None)


FRESHNESS_WINDOW = 300.0  # seconds — handshakes older than this are rejected


def _signed_material(signing_pub: str, ephemeral_pub: str, timestamp) -> bytes:
    return f"{signing_pub}:{ephemeral_pub}:{timestamp}".encode()


def handshake_offer(identity: DeviceIdentityKeys) -> tuple[dict, SessionCrypto]:
    session = SessionCrypto(identity)
    ts = time.time()
    offer = {
        "type": "e2e_offer",
        "signingPub": identity.signing_pub_b64,
        "ephemeralPub": session.ephemeral_pub_b64,
        "timestamp": ts,
        "signature": identity.sign(_signed_material(
            identity.signing_pub_b64, session.ephemeral_pub_b64, ts
        )),
    }
    return offer, session


def handshake_accept(identity: DeviceIdentityKeys, offer: dict) -> tuple[dict, SessionCrypto]:
    """Verify the offer (signature + freshness) BEFORE deriving any key."""
    signing_pub = str(offer.get("signingPub", ""))
    ephemeral_pub = str(offer.get("ephemeralPub", ""))
    ts = offer.get("timestamp")
    sig = str(offer.get("signature", ""))

    if not isinstance(ts, (int, float)) or abs(time.time() - ts) > FRESHNESS_WINDOW:
        raise ValueError("offer timestamp outside freshness window — replay suspected")
    if not sig or not identity.verify(sig, _signed_material(signing_pub, ephemeral_pub, ts), signing_pub):
        raise ValueError("offer signature invalid — possible MITM")

    session = SessionCrypto(identity)
    session.derive_key(ephemeral_pub, initiator=False)

    ts2 = time.time()
    header = f"{identity.signing_pub_b64}:{session.ephemeral_pub_b64}:{ts2}"
    response = {
        "type": "e2e_accept",
        "signingPub": identity.signing_pub_b64,
        "ephemeralPub": session.ephemeral_pub_b64,
        "signature": identity.sign(header.encode()),
        "peerSigningPub": signing_pub,
        "timestamp": ts2,
    }
    return response, session


def handshake_complete(
    identity: DeviceIdentityKeys,
    response: dict,
    session: SessionCrypto,
    initiator: bool = True,
) -> bool:
    """Verify the response signature + freshness BEFORE deriving keys."""
    signing_pub = str(response.get("signingPub", ""))
    ephemeral_pub = str(response.get("ephemeralPub", ""))
    ts = response.get("timestamp")
    sig = str(response.get("signature", ""))

    if not isinstance(ts, (int, float)) or abs(time.time() - ts) > FRESHNESS_WINDOW:
        return False
    if not sig:
        return False
    if not identity.verify(sig, _signed_material(signing_pub, ephemeral_pub, ts), signing_pub):
        return False

    session.derive_key(ephemeral_pub, initiator=initiator)
    return True


class PeerTrustStore:
    """Trust-on-first-use pinning of peer signing keys, keyed by ip (or ip:port).

    Protects against active MITM: once a key is recorded for an address,
    a different key on later connections is rejected. If a device is
    legitimately reinstalled, delete the peers.json file to re-pin.
    """

    def __init__(self, path: Optional[str] = None):
        if path is None:
            base = os.path.dirname(os.path.abspath(
                os.path.expanduser("~/.syncflow/identity")
            ))
            path = os.path.join(base, "peers.json")
        self.path = path
        self._peers: dict = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("peers"), dict):
                    self._peers = data["peers"]
        except Exception:
            self._peers = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump({"peers": self._peers}, f, indent=2)
            os.chmod(self.path, 0o600)
        except Exception:
            pass

    def check(self, key: str, signing_pub: str, name: str = "") -> tuple[bool, str]:
        if not signing_pub:
            return False, "missing peer key"
        record = self._peers.get(key)
        if record is None:
            self._peers[key] = {
                "pub": signing_pub,
                "name": name[:64],
                "firstSeen": time.time(),
                "lastSeen": time.time(),
            }
            self._save()
            return True, "pinned on first contact"
        if record.get("pub") == signing_pub:
            record["lastSeen"] = time.time()
            if name:
                record["name"] = name[:64]
            self._save()
            return True, "pinned key matches"
        return False, (
            f"peer identity for {key} CHANGED (possible MITM) — if the device "
            f"was reinstalled, delete {self.path} to re-pin"
        )
