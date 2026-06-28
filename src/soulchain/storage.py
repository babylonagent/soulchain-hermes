"""
SoulChain storage layer — encrypted blob storage adapters.

Adapters:
  - LocalStorage: stores encrypted blobs on local disk (default, free)
  - PinataStorage: uploads to IPFS via Pinata API
  - MockStorage: in-memory (testing only)

All adapters implement the StorageAdapter interface:
  upload(data: bytes, filename: str) -> str  (returns CID/path)
  download(cid: str) -> bytes
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

import requests


class StorageAdapter:
    """Base class for storage adapters."""

    def upload(self, data: bytes, filename: str) -> str:
        raise NotImplementedError

    def download(self, cid: str) -> bytes:
        raise NotImplementedError


class LocalStorage(StorageAdapter):
    """Store encrypted blobs on local disk."""

    def __init__(self, base_dir: str = None):
        self.base_dir = Path(base_dir or os.path.expanduser("~/.soulchain/storage"))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def upload(self, data: bytes, filename: str) -> str:
        """Store blob locally. Returns CID as 'local:<hash>'."""
        h = hashlib.sha256(data).hexdigest()
        cid = f"local:{h}"
        blob_path = self.base_dir / h
        blob_path.write_bytes(data)
        return cid

    def download(self, cid: str) -> bytes:
        """Retrieve blob from local storage."""
        if not cid.startswith("local:"):
            raise ValueError(f"LocalStorage can't download non-local CID: {cid}")
        h = cid.split(":", 1)[1]
        blob_path = self.base_dir / h
        if not blob_path.exists():
            raise FileNotFoundError(f"No blob for {cid}")
        return blob_path.read_bytes()

    def exists(self, cid: str) -> bool:
        if not cid.startswith("local:"):
            return False
        h = cid.split(":", 1)[1]
        return (self.base_dir / h).exists()


class PinataStorage(StorageAdapter):
    """Upload encrypted blobs to IPFS via Pinata."""

    PINATA_API = "https://api.pinata.cloud"

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key

    def upload(self, data: bytes, filename: str) -> str:
        """Upload to IPFS. Returns IPFS CID."""
        files = {"file": (filename, data)}
        headers = {
            "pinata_api_key": self.api_key,
            "pinata_secret_api_key": self.secret_key,
        }
        resp = requests.post(
            f"{self.PINATA_API}/pinning/pinFileToIPFS",
            files=files,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        cid = resp.json()["IpfsHash"]
        return f"ipfs:{cid}"

    def download(self, cid: str) -> bytes:
        """Download from IPFS via public gateway."""
        if cid.startswith("ipfs:"):
            cid = cid.split(":", 1)[1]
        resp = requests.get(f"https://ipfs.io/ipfs/{cid}", timeout=30)
        resp.raise_for_status()
        return resp.content


class MockStorage(StorageAdapter):
    """In-memory storage (testing only)."""

    def __init__(self):
        self._store: dict[str, bytes] = {}

    def upload(self, data: bytes, filename: str) -> str:
        h = hashlib.sha256(data).hexdigest()
        cid = f"mock:{h}"
        self._store[cid] = data
        return cid

    def download(self, cid: str) -> bytes:
        if cid not in self._store:
            raise FileNotFoundError(f"No blob for {cid}")
        return self._store[cid]


def create_storage(config: dict) -> StorageAdapter:
    """Factory: create storage adapter from config."""
    storage_type = config.get("storage", "local")

    if storage_type == "local":
        storage_dir = config.get("storagePath")
        return LocalStorage(storage_dir)

    elif storage_type == "pinata":
        api_key = os.environ.get("PINATA_API_KEY", config.get("pinataApiKey", ""))
        secret = os.environ.get("PINATA_SECRET_KEY", config.get("pinataSecretKey", ""))
        if not api_key or not secret:
            raise ValueError("Pinata storage requires PINATA_API_KEY and PINATA_SECRET_KEY")
        return PinataStorage(api_key, secret)

    elif storage_type == "mock":
        return MockStorage()

    else:
        raise ValueError(f"Unknown storage type: {storage_type}")
