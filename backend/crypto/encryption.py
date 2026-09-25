import os
from typing import Optional


class FileEncryptor:
    def __init__(self, key: Optional[bytes] = None):
        self.key = key or os.urandom(32)

    def encrypt_file(self, input_path: str, output_path: str) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(12)
        aesgcm = AESGCM(self.key)

        with open(input_path, "rb") as f:
            plaintext = f.read()

        ciphertext = aesgcm.encrypt(nonce, plaintext, None)

        with open(output_path, "wb") as f:
            f.write(nonce)
            f.write(ciphertext)

        return output_path

    def decrypt_file(self, input_path: str, output_path: str) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        with open(input_path, "rb") as f:
            nonce = f.read(12)
            ciphertext = f.read()

        aesgcm = AESGCM(self.key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        with open(output_path, "wb") as f:
            f.write(plaintext)

        return output_path

    def encrypt_bytes(self, data: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(12)
        aesgcm = AESGCM(self.key)
        return nonce + aesgcm.encrypt(nonce, data, None)

    def decrypt_bytes(self, data: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = data[:12]
        ciphertext = data[12:]
        aesgcm = AESGCM(self.key)
        return aesgcm.decrypt(nonce, ciphertext, None)
