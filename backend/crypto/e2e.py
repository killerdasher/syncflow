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

    MITM cannot decrypt because no shared secret ever crosses the wire —
    only ephemeral public keys. Even with the public keys in transit,
    computing the shared secret requires the private key.
    """

    def __init__(self, identity: DeviceIdentityKeys):
        self.identity = identity
        self.ephemeral = X25519PrivateKey.generate()
        self.shared_key: Optional[bytes] = None
        self.nonce_counter = 0

    @property
    def ephemeral_pub_b64(self) -> str:
        return _b64e(self.ephemeral.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ))

    def derive_key(self, peer_ephemeral_pub_b64: str) -> bytes:
        peer_pub = X25519PublicKey.from_public_bytes(_b64d(peer_ephemeral_pub_b64))
        shared = self.ephemeral.exchange(peer_pub)

        self.shared_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"syncflow-e2e-v1",
            info=b"transfer-encryption",
        ).derive(shared)

        return self.shared_key

    def encrypt(self, plaintext: bytes) -> bytes:
        if not self.shared_key:
            raise RuntimeError("Key not derived yet")

        self.nonce_counter += 1
        nonce = self.nonce_counter.to_bytes(12, "big")
        aesgcm = AESGCM(self.shared_key)
        ct = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ct

    def decrypt(self, blob: bytes) -> bytes:
        if not self.shared_key:
            raise RuntimeError("Key not derived yet")

        nonce = blob[:12]
        ct = blob[12:]
        aesgcm = AESGCM(self.shared_key)
        return aesgcm.decrypt(nonce, ct, None)


def handshake_offer(identity: DeviceIdentityKeys) -> tuple[dict, SessionCrypto]:
    session = SessionCrypto(identity)
    offer = {
        "type": "e2e_offer",
        "signingPub": identity.signing_pub_b64,
        "ephemeralPub": session.ephemeral_pub_b64,
        "timestamp": time.time(),
    }
    return offer, session


def handshake_accept(identity: DeviceIdentityKeys, offer: dict) -> tuple[dict, SessionCrypto]:
    session = SessionCrypto(identity)
    session.derive_key(offer["ephemeralPub"])

    ts = time.time()
    header = f"{identity.signing_pub_b64}:{session.ephemeral_pub_b64}:{ts}"
    signature = identity.sign(header.encode())

    response = {
        "type": "e2e_accept",
        "signingPub": identity.signing_pub_b64,
        "ephemeralPub": session.ephemeral_pub_b64,
        "signature": signature,
        "peerSigningPub": offer["signingPub"],
        "timestamp": ts,
    }
    return response, session


def handshake_complete(identity: DeviceIdentityKeys, response: dict, session: SessionCrypto) -> bool:
    session.derive_key(response["ephemeralPub"])

    header = f"{response['signingPub']}:{response['ephemeralPub']}:{response['timestamp']}"
    valid = identity.verify(response["signature"], header.encode(), response["signingPub"])
    return valid
