"""
SoulChain core engine — shared logic for all sync modes.

Hashes, signs, and anchors Hermes identity files on Base via SoulRegistry.
Supports three sync modes: on-write, interval, manual.
"""
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct

# Crypto + storage (Phase 3)
from .crypto import SoulCryptoProvider, SoulKeypair, EncryptedData, derive_document_key
from .storage import StorageAdapter, LocalStorage, create_storage

logger = logging.getLogger("soulchain")

# ─── Constants ────────────────────────────────────────────────────────────────

CONTRACT_ADDRESS = "0x2AE3F15CAD486226Af839ae8FB4BbA08428283A2"
EXPLORER = "https://basescan.org"

DEFAULT_CONFIG = {
    "chain": {
        "rpcUrl": "https://mainnet.base.org",
        "chainId": 8453,
        "contractAddress": CONTRACT_ADDRESS,
        "explorer": EXPLORER,
    },
    "trackedFiles": {
        "SOUL": {"docType": 0, "path": "~/.hermes/SOUL.md"},
        "MEMORY": {"docType": 1, "path": "~/.hermes/memories/MEMORY.md"},
        "USER": {"docType": 3, "path": "~/.hermes/memories/USER.md"},
        "IDENTITY": {"docType": 10, "path": "~/.hermes/config.yaml"},
    },
    "syncMode": "on-write",
    "syncIntervalSec": 300,
    "debounceMs": 2000,
    "gasLimit": 250000,
}

# Doc type names for display
DOC_TYPE_NAMES = {
    0: "SOUL", 1: "MEMORY", 2: "AGENTS", 3: "USER",
    4: "DAILY", 5: "CHAT", 6: "LOVE_MAP", 7: "MUSING",
    8: "COACHING", 9: "TOOLS", 10: "IDENTITY",
}

SOUL_REGISTRY_ABI = [
    {"inputs": [], "name": "registerSoul", "outputs": [],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [
        {"name": "docType", "type": "uint8"},
        {"name": "contentHash", "type": "bytes32"},
        {"name": "encryptedHash", "type": "bytes32"},
        {"name": "storageCid", "type": "string"},
        {"name": "signature", "type": "bytes"},
    ], "name": "writeDocument", "outputs": [],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [
        {"name": "agent", "type": "address"},
        {"name": "docType", "type": "uint8"},
    ], "name": "latestDocument", "outputs": [
        {"components": [
            {"name": "contentHash", "type": "bytes32"},
            {"name": "encryptedHash", "type": "bytes32"},
            {"name": "storageCid", "type": "string"},
            {"name": "docType", "type": "uint8"},
            {"name": "timestamp", "type": "uint64"},
            {"name": "version", "type": "uint32"},
            {"name": "prevHash", "type": "bytes32"},
            {"name": "signature", "type": "bytes"},
        ], "name": "", "type": "tuple"},
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [
        {"name": "agent", "type": "address"},
        {"name": "docType", "type": "uint8"},
        {"name": "version", "type": "uint32"},
    ], "name": "documentAt", "outputs": [
        {"components": [
            {"name": "contentHash", "type": "bytes32"},
            {"name": "encryptedHash", "type": "bytes32"},
            {"name": "storageCid", "type": "string"},
            {"name": "docType", "type": "uint8"},
            {"name": "timestamp", "type": "uint64"},
            {"name": "version", "type": "uint32"},
            {"name": "prevHash", "type": "bytes32"},
            {"name": "signature", "type": "bytes"},
        ], "name": "", "type": "tuple"},
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [
        {"name": "agent", "type": "address"},
        {"name": "docType", "type": "uint8"},
    ], "name": "documentCount", "outputs": [{"name": "", "type": "uint32"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [
        {"name": "agent", "type": "address"},
        {"name": "docType", "type": "uint8"},
        {"name": "version", "type": "uint32"},
        {"name": "expectedHash", "type": "bytes32"},
    ], "name": "verifyDocument", "outputs": [{"name": "", "type": "bool"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "", "type": "address"}],
     "name": "registered", "outputs": [{"name": "", "type": "bool"}],
     "stateMutability": "view", "type": "function"},
    # ── Phase 3: Access grants ──
    {"inputs": [
        {"name": "reader", "type": "address"},
        {"name": "docType", "type": "uint8"},
    ], "name": "grantAccess", "outputs": [],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [
        {"name": "reader", "type": "address"},
        {"name": "docType", "type": "uint8"},
    ], "name": "revokeAccess", "outputs": [],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [
        {"name": "agent", "type": "address"},
        {"name": "reader", "type": "address"},
        {"name": "docType", "type": "uint8"},
    ], "name": "hasAccess", "outputs": [{"name": "", "type": "bool"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [
        {"name": "reader", "type": "address"},
        {"name": "docType", "type": "uint8"},
        {"name": "encryptedKey", "type": "bytes"},
    ], "name": "storeAccessKey", "outputs": [],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [
        {"name": "owner", "type": "address"},
        {"name": "reader", "type": "address"},
        {"name": "docType", "type": "uint8"},
    ], "name": "getAccessKey", "outputs": [{"name": "", "type": "bytes"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [
        {"name": "reader", "type": "address"},
        {"name": "docType", "type": "uint8"},
    ], "name": "removeAccessKey", "outputs": [],
     "stateMutability": "nonpayable", "type": "function"},
    # ── Phase 3: Multi-agent hierarchy ──
    {"inputs": [{"name": "child", "type": "address"}],
     "name": "registerChild", "outputs": [],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "", "type": "address"}],
     "name": "getChildren", "outputs": [{"name": "", "type": "address[]"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "", "type": "address"}],
     "name": "getParent", "outputs": [{"name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"},
]


class SoulChainEngine:
    """Core anchoring engine. Mode-agnostic — handles hashing, signing, tx."""

    def __init__(self, private_key: str, rpc_url: str = None, config: dict = None,
                 crypto: SoulCryptoProvider = None, storage: StorageAdapter = None):
        self.account = Account.from_key(private_key)
        self.config = config or DEFAULT_CONFIG

        # Crypto provider (optional — enables encryption + Ed25519 signatures)
        self.crypto = crypto

        # Storage adapter (optional — stores encrypted blobs off-chain)
        self.storage = storage or create_storage(self.config)

        # Resolve RPC URL
        if rpc_url:
            self.rpc_url = rpc_url
        elif config and "chain" in config and "rpcUrl" in config["chain"]:
            self.rpc_url = config["chain"]["rpcUrl"]
        else:
            alchemy_key = os.environ.get("BASE_ALCHEMY_KEY", "")
            if alchemy_key:
                self.rpc_url = f"https://base-mainnet.g.alchemy.com/v2/{alchemy_key}"
            else:
                self.rpc_url = "https://mainnet.base.org"

        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        if not self.w3.is_connected():
            raise RuntimeError(f"Cannot connect to {self.rpc_url}")

        contract_addr = self.config.get("chain", {}).get(
            "contractAddress", CONTRACT_ADDRESS
        )
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(contract_addr),
            abi=SOUL_REGISTRY_ABI,
        )
        
        # Chain ID from config (allows multi-chain support)
        self._chain_id = self.config.get("chain", {}).get("chainId", 8453)

        # State cache: track last anchored hashes to avoid redundant txs
        self._last_hashes: dict[int, str] = {}
        self._refresh_chain_state()

    def _refresh_chain_state(self):
        """Load latest on-chain hashes for all tracked doc types."""
        for name, info in self.config["trackedFiles"].items():
            dt = info["docType"]
            try:
                latest = self.contract.functions.latestDocument(
                    self.account.address, dt
                ).call()
                if latest[0] != b'\x00' * 32:
                    self._last_hashes[dt] = "0x" + latest[0].hex()
            except Exception:
                pass

    # ─── Public API ───────────────────────────────────────────────────────

    @property
    def address(self) -> str:
        return self.account.address

    @property
    def balance(self) -> float:
        return self.w3.from_wei(self.w3.eth.get_balance(self.account.address), "ether")

    def is_registered(self) -> bool:
        return self.contract.functions.registered(self.account.address).call()

    def register_soul(self) -> Optional[str]:
        """One-time soul registration."""
        if self.is_registered():
            logger.info("Soul already registered")
            return None

        nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
        base_fee = self.w3.eth.get_block("latest")["baseFeePerGas"]
        priority_fee = max(1000, self.w3.eth.max_priority_fee)
        max_fee = int(base_fee * 2) + priority_fee

        tx = self.contract.functions.registerSoul().build_transaction({
            "from": self.account.address,
            "nonce": nonce,
            "gas": 100000,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority_fee,
            "chainId": self._chain_id,
            "type": 2,
        })
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        if receipt["status"] == 1:
            logger.info(f"Soul registered: {EXPLORER}/tx/{tx_hash.hex()}")
            return tx_hash.hex()
        logger.error("Soul registration failed")
        return None

    def hash_file(self, filepath: str) -> Optional[str]:
        """SHA-256 hash a file. Returns hex string or None."""
        path = Path(filepath).expanduser()
        if not path.exists():
            return None
        content = path.read_bytes()
        return "0x" + hashlib.sha256(content).hexdigest()

    def needs_anchor(self, filepath: str, doc_type: int) -> bool:
        """Check if file hash differs from on-chain."""
        local_hash = self.hash_file(filepath)
        if local_hash is None:
            return False
        return self._last_hashes.get(doc_type) != local_hash

    def anchor_file(self, filepath: str, doc_type: int, force: bool = False) -> Optional[str]:
        """
        Hash, sign, and anchor a file on-chain.
        If crypto provider is set: encrypts content, uploads to storage, anchors both hashes.
        Returns tx hash if anchored, None if skipped/failed.
        """
        path = Path(filepath).expanduser()
        if not path.exists():
            logger.warning(f"File not found: {filepath}")
            return None

        content = path.read_bytes()
        content_hash = "0x" + hashlib.sha256(content).hexdigest()

        # Skip if unchanged (unless forced)
        if not force and self._last_hashes.get(doc_type) == content_hash:
            logger.debug(f"Skip {filepath}: unchanged")
            return None

        # Determine version for key derivation
        doc_type_name = DOC_TYPE_NAMES.get(doc_type, f"type_{doc_type}").lower()
        try:
            count = self.contract.functions.documentCount(
                self.account.address, doc_type
            ).call()
            version = count
        except Exception:
            version = 0

        # Encrypt + upload if crypto provider is available
        if self.crypto:
            enc_data = self.crypto.encrypt_document(content, doc_type_name, version)
            enc_blob = enc_data.to_blob()
            encrypted_hash = "0x" + hashlib.sha256(enc_blob).hexdigest()

            # Upload encrypted blob to storage
            storage_cid = self.storage.upload(enc_blob, f"{doc_type_name}_v{version}.enc")
            logger.info(f"🔐 Encrypted {doc_type_name}: {len(content)}B → {len(enc_blob)}B, stored: {storage_cid[:40]}")

            # Sign with Ed25519 (crypto provider)
            signature = self.crypto.sign_hash(content_hash)
        else:
            # Phase 2 fallback: no encryption, EIP-191 signature
            encrypted_hash = content_hash
            storage_cid = f"local:{filepath}"
            msg = encode_defunct(hexstr=content_hash)
            signature = self.account.sign_message(msg).signature

        try:
            gas_estimate = self.contract.functions.writeDocument(
                doc_type,
                bytes.fromhex(content_hash[2:]),
                bytes.fromhex(encrypted_hash[2:]),
                storage_cid,
                signature,
            ).estimate_gas({"from": self.account.address})
            gas_limit = int(gas_estimate * 1.3)
        except Exception:
            gas_limit = self.config.get("gasLimit", 250000)

        nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
        base_fee = self.w3.eth.get_block("latest")["baseFeePerGas"]
        priority_fee = max(1000, self.w3.eth.max_priority_fee)
        max_fee = int(base_fee * 2) + priority_fee

        tx = self.contract.functions.writeDocument(
            doc_type,
            bytes.fromhex(content_hash[2:]),
            bytes.fromhex(encrypted_hash[2:]),
            storage_cid,
            signature,
        ).build_transaction({
            "from": self.account.address,
            "nonce": nonce,
            "gas": gas_limit,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority_fee,
            "chainId": self._chain_id,
            "type": 2,
        })

        signed_tx = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        if receipt["status"] == 1:
            self._last_hashes[doc_type] = content_hash
            name = DOC_TYPE_NAMES.get(doc_type, f"type_{doc_type}")
            logger.info(f"✅ {name} anchored: {EXPLORER}/tx/{tx_hash.hex()}")
            return tx_hash.hex()
        else:
            logger.error(f"❌ {filepath} anchor failed (reverted)")
            return None

    def anchor_all(self, force: bool = False) -> list[dict]:
        """Anchor all tracked files that changed. Returns list of results."""
        results = []
        for name, info in self.config["trackedFiles"].items():
            filepath = info["path"]
            doc_type = info["docType"]
            local_hash = self.hash_file(filepath)

            if local_hash is None:
                results.append({"name": name, "status": "missing", "path": filepath})
                continue

            if not force and self._last_hashes.get(doc_type) == local_hash:
                results.append({
                    "name": name, "status": "unchanged", "path": filepath,
                    "hash": local_hash,
                })
                continue

            tx = self.anchor_file(filepath, doc_type, force=force)
            results.append({
                "name": name,
                "status": "anchored" if tx else "failed",
                "path": filepath,
                "hash": local_hash,
                "tx": tx,
            })
        return results

    def get_status(self) -> list[dict]:
        """Get on-chain status for all tracked files."""
        statuses = []
        for name, info in self.config["trackedFiles"].items():
            dt = info["docType"]
            filepath = info["path"]
            count = self.contract.functions.documentCount(
                self.account.address, dt
            ).call()
            local_hash = self.hash_file(filepath)
            if count > 0:
                latest = self.contract.functions.latestDocument(
                    self.account.address, dt
                ).call()
                chain_hash = "0x" + latest[0].hex()
                match = local_hash == chain_hash if local_hash else False
                statuses.append({
                    "name": name, "docType": dt, "path": filepath,
                    "version": latest[5], "timestamp": latest[4],
                    "onChainHash": chain_hash, "localHash": local_hash,
                    "verified": match, "versionCount": count,
                })
            else:
                statuses.append({
                    "name": name, "docType": dt, "path": filepath,
                    "version": None, "versionCount": 0,
                    "verified": False,
                })
        return statuses

    def verify_all(self) -> list[dict]:
        """Verify local files match on-chain hashes."""
        results = []
        for name, info in self.config["trackedFiles"].items():
            dt = info["docType"]
            filepath = info["path"]
            local_hash = self.hash_file(filepath)
            if local_hash is None:
                results.append({"name": name, "verified": False, "reason": "file_missing"})
                continue
            try:
                latest = self.contract.functions.latestDocument(
                    self.account.address, dt
                ).call()
                chain_hash = "0x" + latest[0].hex()
                match = local_hash == chain_hash
                results.append({
                    "name": name, "verified": match,
                    "local": local_hash, "onChain": chain_hash,
                    "version": latest[5],
                })
            except Exception:
                results.append({"name": name, "verified": False, "reason": "no_onchain_version"})
        return results

    def restore_file(self, doc_type: int, version: int = None) -> Optional[bytes]:
        """
        Restore a file's content from on-chain + storage.
        Downloads encrypted blob from storage, decrypts with crypto provider.
        """
        if not self.crypto:
            logger.error("Cannot restore: no crypto provider configured")
            return None

        try:
            if version is None:
                doc = self.contract.functions.latestDocument(
                    self.account.address, doc_type
                ).call()
            else:
                doc = self.contract.functions.documentAt(
                    self.account.address, doc_type, version
                ).call()

            content_hash = "0x" + doc[0].hex()
            cid = doc[2]
            actual_version = doc[5]

            if not cid or cid == "":
                logger.error(f"No storage CID for doc type {doc_type} v{actual_version}")
                return None

            logger.info(f"Downloading {cid[:40]}...")
            enc_blob = self.storage.download(cid)

            doc_type_name = DOC_TYPE_NAMES.get(doc_type, f"type_{doc_type}").lower()
            enc_data = EncryptedData.from_blob(enc_blob)
            plaintext = self.crypto.decrypt_document(enc_data, doc_type_name, actual_version)

            # Verify restored hash matches on-chain
            restored_hash = "0x" + hashlib.sha256(plaintext).hexdigest()
            if restored_hash != content_hash:
                logger.error("Hash mismatch! Restored content doesn't match on-chain record")
                return None

            logger.info(f"✅ Restored {doc_type_name} v{actual_version}: {len(plaintext)}B")
            return plaintext

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return None

    # ─── Phase 3: Access Grants ───────────────────────────────────────────

    def grant_access(self, reader: str, doc_type: int) -> Optional[str]:
        """Grant read access to another address for a doc type."""
        if not self.is_registered():
            logger.error("Soul not registered")
            return None
        reader = Web3.to_checksum_address(reader)
        nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
        base_fee = self.w3.eth.get_block("latest")["baseFeePerGas"]
        priority_fee = max(1000, self.w3.eth.max_priority_fee)
        max_fee = int(base_fee * 2) + priority_fee
        tx = self.contract.functions.grantAccess(reader, doc_type).build_transaction({
            "from": self.account.address,
            "nonce": nonce, "gas": 100000,
            "maxFeePerGas": max_fee, "maxPriorityFeePerGas": priority_fee,
            "chainId": self._chain_id, "type": 2,
        })
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        if receipt["status"] == 1:
            logger.info(f"✅ Access granted: {reader} for doc type {doc_type}")
            return tx_hash.hex()
        logger.error("Access grant failed")
        return None

    def revoke_access(self, reader: str, doc_type: int) -> Optional[str]:
        """Revoke read access from an address for a doc type.
        
        Note: The contract now deletes accessKeys on revokeAccess.
        If using an older contract version, call removeAccessKey separately.
        """
        if not self.is_registered():
            logger.error("Soul not registered")
            return None
        reader = Web3.to_checksum_address(reader)
        nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
        base_fee = self.w3.eth.get_block("latest")["baseFeePerGas"]
        priority_fee = max(1000, self.w3.eth.max_priority_fee)
        max_fee = int(base_fee * 2) + priority_fee
        tx = self.contract.functions.revokeAccess(reader, doc_type).build_transaction({
            "from": self.account.address,
            "nonce": nonce, "gas": 100000,
            "maxFeePerGas": max_fee, "maxPriorityFeePerGas": priority_fee,
            "chainId": self._chain_id, "type": 2,
        })
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        if receipt["status"] == 1:
            logger.info(f"✅ Access revoked (incl. access key) for {reader} doc type {doc_type}")
            return tx_hash.hex()
        logger.error("Access revoke failed")
        return None

    def has_access(self, agent: str, reader: str, doc_type: int) -> bool:
        """Check if reader has access to agent's doc type."""
        agent = Web3.to_checksum_address(agent)
        reader = Web3.to_checksum_address(reader)
        return self.contract.functions.hasAccess(agent, reader, doc_type).call()

    def get_access_grants_summary(self) -> list[dict]:
        """Check access status for all tracked doc types against the caller's own address.
        Returns a summary of whether the owner can access each doc type (self-access always true for registered souls)."""
        results = []
        for name, info in self.config["trackedFiles"].items():
            dt = info["docType"]
            has = self.has_access(self.account.address, self.account.address, dt)
            results.append({
                "name": name, "docType": dt, "selfAccess": has,
            })
        return results

    # ─── Phase 3: Multi-Agent Hierarchy ───────────────────────────────────

    def register_child(self, child_address: str) -> Optional[str]:
        """Register a child agent under this soul."""
        if not self.is_registered():
            logger.error("Soul not registered")
            return None
        child_address = Web3.to_checksum_address(child_address)
        nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
        base_fee = self.w3.eth.get_block("latest")["baseFeePerGas"]
        priority_fee = max(1000, self.w3.eth.max_priority_fee)
        max_fee = int(base_fee * 2) + priority_fee
        tx = self.contract.functions.registerChild(child_address).build_transaction({
            "from": self.account.address,
            "nonce": nonce, "gas": 100000,
            "maxFeePerGas": max_fee, "maxPriorityFeePerGas": priority_fee,
            "chainId": self._chain_id, "type": 2,
        })
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        if receipt["status"] == 1:
            logger.info(f"✅ Child registered: {child_address}")
            return tx_hash.hex()
        logger.error("Child registration failed")
        return None

    def get_children(self) -> list[str]:
        """Get all child agent addresses."""
        raw = self.contract.functions.getChildren(self.account.address).call()
        return [addr for addr in raw if addr != "0x" + "00" * 20]

    def get_parent(self) -> str:
        """Get parent agent address (if any)."""
        return self.contract.functions.getParent(self.account.address).call()

    def get_hierarchy(self) -> dict:
        """Get full hierarchy: parent + children."""
        parent = self.get_parent()
        children = self.get_children()
        return {
            "agent": self.account.address,
            "parent": parent if parent != "0x" + "00" * 20 else None,
            "children": children,
            "childCount": len(children),
        }


def load_config(config_path: str = None) -> dict:
    """Load soulchain.config.json, falling back to defaults."""
    if config_path is None:
        # Search in standard locations
        candidates = [
            os.environ.get("SOULCHAIN_CONFIG"),
            os.path.expanduser("~/.hermes/soulchain.config.json"),
            os.path.expanduser("~/soulchain-hermes/soulchain.config.json"),
            "soulchain.config.json",
        ]
        for c in candidates:
            if c and os.path.exists(c):
                config_path = c
                break

    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            user_config = json.load(f)
        # Merge with defaults
        merged = DEFAULT_CONFIG.copy()
        merged.update(user_config)
        return merged

    return DEFAULT_CONFIG.copy()


def load_private_key() -> str:
    """Load private key from env or keystore."""
    # 1. Direct env var
    key = os.environ.get("SOULCHAIN_PRIVATE_KEY")
    if key:
        return key

    # 2. Wallet file via env var
    wallet_file = os.environ.get("SOULCHAIN_PRIVATE_KEY_FILE")
    if wallet_file:
        wallet_path = Path(wallet_file)
        if wallet_path.exists():
            for line in wallet_path.read_text().splitlines():
                if "PRIVATE_KEY" in line and "=" in line and not line.startswith("#"):
                    return line.split("=", 1)[1].strip()

    # 3. SoulChain keystore
    keystore_path = Path(os.environ.get(
        "SOULCHAIN_KEYSTORE", os.path.expanduser("~/.soulchain/keystore.json")
    ))
    if keystore_path.exists():
        import getpass
        with open(keystore_path) as f:
            keystore = json.load(f)
        password = os.environ.get("SOULCHAIN_KEYSTORE_PASSWORD") or getpass.getpass(
            "Enter keystore password: "
        )
        return Account.decrypt(keystore, password).hex()

    raise RuntimeError(
        "No private key found. Set SOULCHAIN_PRIVATE_KEY or "
        "SOULCHAIN_PRIVATE_KEY_FILE, or configure a keystore."
    )
