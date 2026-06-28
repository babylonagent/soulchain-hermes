"""
SoulChain crypto layer — Ed25519 keypairs, AES-256-GCM encryption, keystore.

Ported from openClause/soulchain TypeScript implementation.

Crypto flow:
  1. Generate Ed25519 keypair (32-byte seed → public key)
  2. Derive per-document symmetric key via HKDF(masterKey, docType:version)
  3. Encrypt file content with AES-256-GCM (iv=12, tag=16, ciphertext)
  4. Sign plaintext SHA-256 hash with Ed25519
  5. Upload encrypted blob (iv+tag+ciphertext) to storage
  6. Anchor on-chain: contentHash, encryptedHash, cid, signature

Keystore:
  - Ed25519 secret key encrypted with argon2id(passphrase) → AES-256-GCM
  - Stored as JSON at ~/.soulchain/keystore.json
"""
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
import nacl.pwhash


# ─── Ed25519 Keypair ──────────────────────────────────────────────────────────

class SoulKeypair:
    """Ed25519 keypair for signing + key derivation."""

    def __init__(self, secret_key: bytes, public_key: bytes = None):
        """Create from 32-byte seed."""
        if len(secret_key) != 32:
            raise ValueError("Secret key must be 32 bytes")
        self.secret_key = secret_key
        self._ed25519 = Ed25519PrivateKey.from_private_bytes(secret_key)
        if public_key is None:
            public_key = self._ed25519.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        self.public_key = public_key

    @classmethod
    def generate(cls) -> "SoulKeypair":
        """Generate a new random keypair."""
        sk = Ed25519PrivateKey.generate()
        secret = sk.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return cls(secret)

    @classmethod
    def from_seed(cls, seed: bytes) -> "SoulKeypair":
        """Create from a 32-byte seed (deterministic)."""
        return cls(seed)

    def sign(self, message: bytes) -> bytes:
        """Sign a message with Ed25519."""
        return self._ed25519.sign(message)

    def verify(self, message: bytes, signature: bytes, public_key: bytes = None) -> bool:
        """Verify a signature."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pk_bytes = public_key or self.public_key
        pk = Ed25519PublicKey.from_public_bytes(pk_bytes)
        try:
            pk.verify(signature, message)
            return True
        except Exception:
            return False

    @property
    def address(self) -> str:
        """Hex-encoded public key — used as the agent's Soul identity."""
        return "0x" + self.public_key.hex()


# ─── AES-256-GCM Encryption ───────────────────────────────────────────────────

class EncryptedData:
    """Result of AES-256-GCM encryption."""

    def __init__(self, ciphertext: bytes, iv: bytes, tag: bytes):
        self.ciphertext = ciphertext
        self.iv = iv  # 12 bytes
        self.tag = tag  # 16 bytes

    def to_blob(self) -> bytes:
        """Serialize to portable format: iv(12) + tag(16) + ciphertext."""
        return self.iv + self.tag + self.ciphertext

    @classmethod
    def from_blob(cls, blob: bytes) -> "EncryptedData":
        """Deserialize from portable format."""
        if len(blob) < 28:
            raise ValueError("Invalid encrypted blob (too short)")
        return cls(
            ciphertext=blob[28:],
            iv=blob[:12],
            tag=blob[12:28],
        )

    @classmethod
    def encrypt(cls, plaintext: bytes, key: bytes) -> "EncryptedData":
        """Encrypt with AES-256-GCM."""
        if len(key) != 32:
            raise ValueError("Key must be 32 bytes for AES-256-GCM")
        iv = secrets.token_bytes(12)
        aesgcm = AESGCM(key)
        # AESGCM.encrypt returns ciphertext+tag concatenated (tag is last 16 bytes)
        ct_and_tag = aesgcm.encrypt(iv, plaintext, associated_data=None)
        ciphertext = ct_and_tag[:-16]
        tag = ct_and_tag[-16:]
        return cls(ciphertext, iv, tag)

    def decrypt(self, key: bytes) -> bytes:
        """Decrypt with AES-256-GCM."""
        if len(key) != 32:
            raise ValueError("Key must be 32 bytes for AES-256-GCM")
        aesgcm = AESGCM(key)
        ct_and_tag = self.ciphertext + self.tag
        return aesgcm.decrypt(self.iv, ct_and_tag, associated_data=None)


# ─── Key Derivation ───────────────────────────────────────────────────────────

def derive_document_key(master_key: bytes, doc_type: str, version: int) -> bytes:
    """
    Derive a per-document symmetric key from the master key.
    Uses HKDF-SHA256 with info = "docType:version".
    Matches the upstream TypeScript implementation.
    """
    info = f"{doc_type}:{version}".encode()
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"",
        info=info,
    )
    return hkdf.derive(master_key)


# ─── Keystore (argon2id + AES-256-GCM) ───────────────────────────────────────

KEYSTORE_VERSION = 1

def create_keystore(secret_key: bytes, passphrase: str) -> dict:
    """
    Encrypt the Ed25519 secret key with argon2id(passphrase) → AES-256-GCM.
    Returns a JSON-serializable keystore dict.
    """
    salt = secrets.token_bytes(16)  # argon2id (libsodium) requires 16-byte salt
    # Use libsodium's argon2id (via pynacl)
    derived = nacl.pwhash.argon2id.kdf(
        size=32,
        password=passphrase.encode(),
        salt=salt,
        opslimit=nacl.pwhash.argon2id.OPSLIMIT_SENSITIVE,
        memlimit=nacl.pwhash.argon2id.MEMLIMIT_SENSITIVE,
    )

    iv = secrets.token_bytes(12)
    aesgcm = AESGCM(derived)
    ct_and_tag = aesgcm.encrypt(iv, secret_key, associated_data=None)
    ciphertext = ct_and_tag[:-16]
    tag = ct_and_tag[-16:]

    return {
        "version": KEYSTORE_VERSION,
        "algorithm": "argon2id",
        "params": {
            "opslimit": nacl.pwhash.argon2id.OPSLIMIT_SENSITIVE,
            "memlimit": nacl.pwhash.argon2id.MEMLIMIT_SENSITIVE,
        },
        "salt": salt.hex(),
        "iv": iv.hex(),
        "ciphertext": ciphertext.hex(),
        "tag": tag.hex(),
    }


def unlock_keystore(keystore: dict, passphrase: str) -> bytes:
    """Unlock a keystore with the passphrase. Returns the 32-byte secret key."""
    salt = bytes.fromhex(keystore["salt"])
    iv = bytes.fromhex(keystore["iv"])
    ciphertext = bytes.fromhex(keystore["ciphertext"])
    tag = bytes.fromhex(keystore["tag"])

    derived = nacl.pwhash.argon2id.kdf(
        size=32,
        password=passphrase.encode(),
        salt=salt,
        opslimit=keystore.get("params", {}).get("opslimit", nacl.pwhash.argon2id.OPSLIMIT_SENSITIVE),
        memlimit=keystore.get("params", {}).get("memlimit", nacl.pwhash.argon2id.MEMLIMIT_SENSITIVE),
    )

    aesgcm = AESGCM(derived)
    ct_and_tag = ciphertext + tag
    return aesgcm.decrypt(iv, ct_and_tag, associated_data=None)


# ─── Keystore File I/O ───────────────────────────────────────────────────────

DEFAULT_KEYSTORE_PATH = os.path.expanduser("~/.soulchain/keystore.json")


def save_keystore(keystore: dict, path: str = None):
    """Save keystore to JSON file."""
    path = path or DEFAULT_KEYSTORE_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # Restrict permissions
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(keystore, f, indent=2)
    Path(path).chmod(0o600)


def load_keystore_file(path: str = None) -> Optional[dict]:
    """Load keystore from JSON file."""
    path = path or DEFAULT_KEYSTORE_PATH
    p = Path(path)
    if not p.exists():
        return None
    with open(path) as f:
        return json.load(f)


# ─── High-Level Crypto Provider ───────────────────────────────────────────────

class SoulCryptoProvider:
    """
    High-level crypto provider matching the upstream CryptoProvider interface.
    Combines keypair + encryption + signing + key derivation.
    """

    def __init__(self, keypair: SoulKeypair):
        self.keypair = keypair

    @classmethod
    def generate(cls) -> "SoulCryptoProvider":
        return cls(SoulKeypair.generate())

    @classmethod
    def from_keystore(cls, keystore_path: str, passphrase: str) -> "SoulCryptoProvider":
        keystore = load_keystore_file(keystore_path)
        if keystore is None:
            raise FileNotFoundError(f"No keystore at {keystore_path}")
        secret = unlock_keystore(keystore, passphrase)
        return cls(SoulKeypair(secret))

    def encrypt_document(self, plaintext: bytes, doc_type: str, version: int) -> EncryptedData:
        """Encrypt a document with a derived per-document key."""
        key = derive_document_key(self.keypair.secret_key, doc_type, version)
        return EncryptedData.encrypt(plaintext, key)

    def decrypt_document(self, encrypted: EncryptedData, doc_type: str, version: int) -> bytes:
        """Decrypt a document with a derived per-document key."""
        key = derive_document_key(self.keypair.secret_key, doc_type, version)
        return encrypted.decrypt(key)

    def sign_hash(self, content_hash_hex: str) -> bytes:
        """Sign a SHA-256 content hash (hex string) with Ed25519."""
        # Sign the raw 32-byte hash
        hash_bytes = bytes.fromhex(content_hash_hex.replace("0x", ""))
        return self.keypair.sign(hash_bytes)

    def verify_signature(self, content_hash_hex: str, signature: bytes, public_key: bytes = None) -> bool:
        """Verify an Ed25519 signature of a content hash."""
        hash_bytes = bytes.fromhex(content_hash_hex.replace("0x", ""))
        return self.keypair.verify(hash_bytes, signature, public_key)

    def save(self, passphrase: str, path: str = None):
        """Save this provider's keypair to an encrypted keystore."""
        keystore = create_keystore(self.keypair.secret_key, passphrase)
        save_keystore(keystore, path)

    @property
    def address(self) -> str:
        return self.keypair.address
