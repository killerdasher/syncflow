import hashlib
import json
import time
from typing import Optional


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_str(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


class Block:
    def __init__(
        self,
        index: int,
        prev_hash: str,
        chunk_hash: str,
        file_name: str,
        chunk_size: int,
        sender_pubkey: str,
        signature: str = "",
        timestamp: Optional[float] = None,
    ):
        self.index = index
        self.prev_hash = prev_hash
        self.chunk_hash = chunk_hash
        self.file_name = file_name
        self.chunk_size = chunk_size
        self.sender_pubkey = sender_pubkey
        self.signature = signature
        self.timestamp = timestamp or time.time()

    def header(self) -> str:
        return json.dumps({
            "index": self.index,
            "prev_hash": self.prev_hash,
            "chunk_hash": self.chunk_hash,
            "file_name": self.file_name,
            "chunk_size": self.chunk_size,
            "sender_pubkey": self.sender_pubkey,
            "timestamp": self.timestamp,
        }, sort_keys=True)

    def block_hash(self) -> str:
        return sha256_str(self.header())

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "chunk_hash": self.chunk_hash,
            "file_name": self.file_name,
            "chunk_size": self.chunk_size,
            "sender_pubkey": self.sender_pubkey,
            "signature": self.signature,
            "timestamp": self.timestamp,
            "block_hash": self.block_hash(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        return cls(
            index=d["index"],
            prev_hash=d["prev_hash"],
            chunk_hash=d["chunk_hash"],
            file_name=d["file_name"],
            chunk_size=d["chunk_size"],
            sender_pubkey=d["sender_pubkey"],
            signature=d.get("signature", ""),
            timestamp=d.get("timestamp", time.time()),
        )


class TransferChain:
    """Blockchain-style hash chain for file transfer verification.

    Each 64KB chunk becomes a block. Block N's header includes Block N-1's
    hash, creating an immutable chain. Tampering with any chunk breaks
    every subsequent block hash, making MITM modification detectable.
    """

    GENESIS_HASH = "0" * 64

    def __init__(self, transfer_id: str, file_name: str, sender_pubkey: str):
        self.transfer_id = transfer_id
        self.file_name = file_name
        self.sender_pubkey = sender_pubkey
        self.blocks: list[Block] = []

    def append_chunk(self, chunk: bytes, signer=None) -> Block:
        prev = self.blocks[-1].block_hash() if self.blocks else self.GENESIS_HASH
        chunk_hash = sha256(chunk)

        block = Block(
            index=len(self.blocks),
            prev_hash=prev,
            chunk_hash=chunk_hash,
            file_name=self.file_name,
            chunk_size=len(chunk),
            sender_pubkey=self.sender_pubkey,
        )

        header = block.header().encode()
        if signer:
            block.signature = signer.sign(header)

        self.blocks.append(block)
        return block

    def merkle_root(self) -> str:
        if not self.blocks:
            return sha256_str("empty")

        hashes = [b.block_hash() for b in self.blocks]

        while len(hashes) > 1:
            if len(hashes) % 2 == 1:
                hashes.append(hashes[-1])
            hashes = [
                sha256_str(hashes[i] + hashes[i + 1])
                for i in range(0, len(hashes), 2)
            ]

        return hashes[0]

    def chain_hash(self) -> str:
        if not self.blocks:
            return self.GENESIS_HASH
        return self.blocks[-1].block_hash()

    def to_manifest(self) -> dict:
        return {
            "transferId": self.transfer_id,
            "fileName": self.file_name,
            "senderPubkey": self.sender_pubkey,
            "blockCount": len(self.blocks),
            "merkleRoot": self.merkle_root(),
            "chainHash": self.chain_hash(),
            "blocks": [b.to_dict() for b in self.blocks],
        }

    def wire_manifest(self) -> dict:
        """Compact manifest: per-block verification happens at receive time,
        so only aggregate hashes travel on the wire (no per-block dump)."""
        return {
            "type": "file_manifest",
            "transferId": self.transfer_id,
            "fileName": self.file_name,
            "senderPubkey": self.sender_pubkey,
            "blockCount": len(self.blocks),
            "merkleRoot": self.merkle_root(),
            "chainHash": self.chain_hash(),
        }

    @staticmethod
    def verify_chunk(
        header_str: str,
        signature: str,
        chunk: bytes,
        expected_index: int,
        expected_prev: str,
        expected_name: str,
        expected_signer: str,
        verify_fn,
    ) -> tuple[bool, str, str]:
        """Verify one streamed block against the running chain.

        Checks: header parses, index/prev-link/file/sender all match what we
        expect, chunk hash + size match the actual plaintext bytes, and the
        Ed25519 signature over the exact header string is valid for the
        authenticated sender key. Returns (ok, reason, block_hash).
        """
        try:
            fields = json.loads(header_str)
        except Exception:
            return False, "block header is not valid JSON", ""

        if not isinstance(fields, dict):
            return False, "block header must be an object", ""

        if fields.get("index") != expected_index:
            return False, f"block index mismatch (got {fields.get('index')}, want {expected_index})", ""
        if fields.get("prev_hash") != expected_prev:
            return False, "chain broken — prev_hash mismatch", ""
        if fields.get("file_name") != expected_name:
            return False, "file_name in signed header does not match expected file", ""
        if fields.get("sender_pubkey") != expected_signer:
            return False, "sender_pubkey in signed header does not match authenticated peer", ""
        if fields.get("chunk_size") != len(chunk):
            return False, "chunk size mismatch", ""
        if fields.get("chunk_hash") != sha256(chunk):
            return False, "chunk hash mismatch — data tampered", ""
        if not signature or not verify_fn(signature, header_str.encode(), expected_signer):
            return False, "block signature invalid", ""

        return True, "", sha256_str(header_str)

    @classmethod
    def verify_manifest(cls, manifest: dict, chunks: list[bytes]) -> tuple[bool, str]:
        blocks = manifest.get("blocks", [])

        if len(blocks) != len(chunks):
            return False, f"Block count {len(blocks)} != chunk count {len(chunks)}"

        prev_hash = cls.GENESIS_HASH
        recomputed_hashes = []

        for i, (block_dict, chunk) in enumerate(zip(blocks, chunks)):
            block = Block.from_dict(block_dict)

            if block.index != i:
                return False, f"Block {i}: index mismatch ({block.index})"

            if block.prev_hash != prev_hash:
                return False, f"Block {i}: chain broken — prev_hash mismatch"

            actual_chunk_hash = sha256(chunk)
            if block.chunk_hash != actual_chunk_hash:
                return False, f"Block {i}: chunk hash mismatch — data tampered"

            if block.chunk_size != len(chunk):
                return False, f"Block {i}: chunk size mismatch"

            recomputed_hashes.append(block.block_hash())
            prev_hash = block.block_hash()

        if recomputed_hashes and recomputed_hashes[-1] != manifest.get("chainHash"):
            return False, "Final chain hash mismatch"

        hash_list = list(recomputed_hashes)
        while len(hash_list) > 1:
            if len(hash_list) % 2 == 1:
                hash_list.append(hash_list[-1])
            hash_list = [
                sha256_str(hash_list[i] + hash_list[i + 1])
                for i in range(0, len(hash_list), 2)
            ]

        recomputed_merkle = hash_list[0] if hash_list else sha256_str("empty")
        if recomputed_merkle != manifest.get("merkleRoot"):
            return False, "Merkle root mismatch"

        return True, "Chain verified: all blocks intact"
